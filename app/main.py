import json
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.instructor_auth import (
    SESSION_KEY,
    credentials_path,
    ensure_instructor_credentials_file,
    instructor_session_ok,
    verify_instructor_login,
)
from app.database import (
    ExamQuestion,
    ExamSession,
    FinalGrade,
    NominatedExam,
    NominatedExamSnapshotQuestion,
    PerformanceLog,
    QuestionAnalysisFeedback,
    Student,
    _is_valid_nominated_access_code,
    generate_unique_exam_code,
    generate_unique_nominated_access_code,
    get_db,
    get_or_create_student,
    init_db,
)
from app.perf_logging import log_performance_event
from app.question_analysis_support import (
    load_question_analysis_context,
    normalize_question_analysis_params,
)
from app.errors import TogetherApiError
from app.education_levels import (
    ALLOWED_LEVEL_IDS,
    DEFAULT_EDUCATION_LEVEL_ID,
    EDUCATION_LEVELS,
    label_for_level,
)
from app.grading_strictness import (
    ALLOWED_STRICTNESS_IDS,
    DEFAULT_GRADING_STRICTNESS,
    GRADING_STRICTNESS_OPTIONS,
    hints_limit_for_strictness,
    label_for_strictness,
)
from app.llm_service import (
    generate_ai_helper_reply,
    generate_question,
    generate_safe_hint,
    grade_answer,
    grade_and_final_combined,
    grade_and_next_question_combined,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["fromjson"] = lambda s: json.loads(s)
templates.env.filters["level_label"] = label_for_level
templates.env.filters["strictness_label"] = label_for_strictness
templates.env.globals["instructor_signed_in"] = instructor_session_ok

_EXAM_ID_IN_PATH = re.compile(r"^/(?:exam|professor/exam)/(\d+)(?:/|$)")


def _exam_session_id_from_path(path: str) -> int | None:
    m = _EXAM_ID_IN_PATH.match(path or "")
    return int(m.group(1)) if m else None


def _exam_session_id_for_http_log(path: str, response: Response | None) -> int | None:
    sid = _exam_session_id_from_path(path)
    if sid is not None:
        return sid
    if response is not None and path in ("/exam/start", "/exam/start-nominated"):
        loc = response.headers.get("location") or response.headers.get("Location")
        if loc:
            pth = urlparse(loc).path if "://" in loc else loc.split("?", 1)[0]
            return _exam_session_id_from_path(pth)
    return None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _s = get_settings()
    ensure_instructor_credentials_file(credentials_path(BASE_DIR, _s))
    # Starlette: use lifespan OR on_event startup — not both. With lifespan set,
    # @app.on_event("startup") is skipped, so DB init must run here.
    init_db()
    yield


app = FastAPI(
    title="Modular Oral-Style Exam System",
    version="0.1.0",
    lifespan=_lifespan,
)
_inst_settings = get_settings()
app.add_middleware(
    SessionMiddleware,
    secret_key=_inst_settings.instructor_session_secret,
    session_cookie="rgee_instructor",
    same_site="lax",
    https_only=False,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/assets", StaticFiles(directory=str(BASE_DIR / "assets")), name="assets")


@app.middleware("http")
async def log_http_timing(request: Request, call_next):
    if request.url.path.startswith("/static") or request.url.path.startswith("/assets"):
        return await call_next(request)
    start = time.perf_counter()
    status: int | str = "error"
    path = request.url.path
    response: Response | None = None
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        exam_session_id = _exam_session_id_for_http_log(path, response)
        log_performance_event(
            "http",
            f"{request.method} {path}",
            (time.perf_counter() - start) * 1000,
            exam_session_id=exam_session_id,
            meta={"status_code": status},
        )

POINTS_PER_QUESTION = 10.0
AI_HELPER_OFFTOPIC_MESSAGE = (
    "I want to help with your exam progress. Please share what part of this question "
    "you want to work on, and I will guide you without giving the final answer."
)
AI_HELPER_NO_HINTS_MESSAGE = "Sorry you ran out of hints cannot chat with AI helper"


def _safe_instructor_next_url(next_url: str) -> str:
    if not isinstance(next_url, str) or not next_url.startswith("/") or next_url.startswith("//"):
        return "/professor"
    return next_url


def _instructor_login_redirect(request: Request) -> RedirectResponse | None:
    if instructor_session_ok(request):
        return None
    raw = request.url.path + ("?" + request.url.query if request.url.query else "")
    return RedirectResponse(
        url=f"/professor/login?next={quote(raw, safe='')}",
        status_code=303,
    )


@app.exception_handler(TogetherApiError)
async def together_api_error_handler(request: Request, exc: TogetherApiError):
    """Return friendly HTML for Together.ai failures."""
    return templates.TemplateResponse(
        request,
        "error.html",
        {"message": "We could not complete that action right now. Please try again."},
        status_code=exc.http_status,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Render HTML error pages so users never see raw API JSON errors."""
    status_code = exc.status_code if isinstance(exc.status_code, int) else 500
    message = "We could not complete that action. Please try again."
    if status_code == 404:
        message = "We could not find that page."
    elif status_code < 500:
        message = "There was a problem with that request. Please check your input and try again."
    return templates.TemplateResponse(
        request,
        "error.html",
        {"message": message},
        status_code=status_code,
    )


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
):
    """Return friendly HTML for validation issues."""
    return templates.TemplateResponse(
        request,
        "error.html",
        {"message": "Some required information is missing or invalid. Please try again."},
        status_code=422,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Final safety net to avoid exposing internal errors to users."""
    logger.exception("Unhandled error for %s %s", request.method, request.url.path)
    return templates.TemplateResponse(
        request,
        "error.html",
        {"message": "Something went wrong on our side. Please try again in a moment."},
        status_code=500,
    )


def _rubric_to_stored(rubric: list | str) -> str:
    if isinstance(rubric, list):
        return json.dumps(rubric, ensure_ascii=False)
    return str(rubric)


def _merge_instructor_note_into_domain_notes(
    domain_notes: str | None, instructor_note: str
) -> str | None:
    ins = (instructor_note or "").strip()
    base = (domain_notes or "").strip()
    if not ins:
        return domain_notes if base else None
    block = f"--- Instructor note ---\n{ins}"
    if not base:
        return block
    return f"{base}\n\n{block}"


def _prior_summary(session: ExamSession, db: Session) -> str:
    rows = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.session_id == session.id)
        .order_by(ExamQuestion.question_index.asc())
        .all()
    )
    if not rows:
        return ""
    parts = []
    for r in rows:
        parts.append(f"[Q{r.question_index + 1}] {r.essay_question[:400]}")
    return "\n".join(parts)


def _earlier_graded_blob(db: Session, session: ExamSession, before_index: int) -> str:
    """Text block of essay + response + grade JSON for questions before index (for combined final prompt)."""
    rows = (
        db.query(ExamQuestion)
        .filter(
            ExamQuestion.session_id == session.id,
            ExamQuestion.question_index < before_index,
        )
        .order_by(ExamQuestion.question_index.asc())
        .all()
    )
    if not rows:
        return ""
    parts = []
    for r in rows:
        parts.append(
            f"--- Question {r.question_index + 1} ---\n"
            f"Essay: {r.essay_question}\n"
            f"Student response: {r.student_response or ''}\n"
            f"Grading JSON: {r.graded_state_p_json or '(none)'}"
        )
    return "\n\n".join(parts)


def _safe_json_dict(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _rubric_items(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except json.JSONDecodeError:
        pass
    text = str(raw).strip()
    return [text] if text else []


def _best_dimension_match(dimension_scores: dict, criterion: str, index: int) -> tuple[str, float | None]:
    if not isinstance(dimension_scores, dict) or not dimension_scores:
        return (f"Criterion {index + 1}", None)
    criterion_words = {w for w in criterion.lower().split() if len(w) > 3}
    for key, value in dimension_scores.items():
        key_words = {w for w in str(key).lower().replace("_", " ").split() if len(w) > 3}
        if criterion_words and key_words and criterion_words.intersection(key_words):
            try:
                return (str(key).replace("_", " ").title(), float(value))
            except (TypeError, ValueError):
                return (str(key).replace("_", " ").title(), None)
    key = list(dimension_scores.keys())[index % len(dimension_scores)]
    try:
        return (str(key).replace("_", " ").title(), float(dimension_scores[key]))
    except (TypeError, ValueError):
        return (str(key).replace("_", " ").title(), None)


def _reference_answer_text(grade_payload: dict, rubric: list[str]) -> str:
    for key in ("reference_answer", "ideal_answer", "model_answer", "expected_answer"):
        value = grade_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if not rubric:
        return "A strong answer should be clear, accurate, and directly address the question prompt."
    joined = "; ".join(rubric)
    return f"A strong answer should cover: {joined}."


def _first_nonempty_str(payload: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _list_or_text(payload: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            items = [str(v).strip() for v in value if str(v).strip()]
            if items:
                return "\n".join(f"- {item}" for item in items)
    return ""


def _rubric_feedback_sections(
    grade_payload: dict, rubric_breakdown: list[dict], rubric: list[str]
) -> dict[str, str]:
    strengths = _list_or_text(
        grade_payload,
        (
            "strengths",
            "strength",
            "what_went_well",
            "positive_feedback",
            "strong_points",
        ),
    )
    improvements = _list_or_text(
        grade_payload,
        (
            "areas_for_improvement",
            "improvements",
            "weaknesses",
            "gaps",
            "needs_improvement",
        ),
    )
    suggestions = _list_or_text(
        grade_payload,
        ("suggestions", "recommendations", "next_steps", "study_suggestions"),
    )
    if not strengths:
        strong_rows = [
            row for row in rubric_breakdown if row.get("score") is not None and float(row["score"]) >= 80
        ]
        if strong_rows:
            strengths = "\n".join(
                f"- {row['criterion']} ({float(row['score']):.1f}%)"
                for row in strong_rows[:3]
            )
        elif rubric:
            strengths = f"- {rubric[0]}"
        else:
            overall = grade_payload.get("overall_percent")
            if isinstance(overall, (int, float)) and float(overall) >= 70:
                strengths = "- Demonstrates a solid baseline understanding of the prompt."
            else:
                strengths = "- Attempts to address the prompt and key concepts."
    if not improvements:
        low_rows = [
            row for row in rubric_breakdown if row.get("score") is not None and float(row["score"]) < 80
        ]
        if low_rows:
            improvements = "\n".join(
                f"- {row['criterion']} ({float(row['score']):.1f}%)"
                for row in low_rows[:3]
            )
        elif rubric:
            improvements = f"- {rubric[min(1, len(rubric) - 1)]}"
        else:
            improvements = "- Needs clearer evidence and tighter alignment to the prompt."
    if not suggestions:
        suggestion_lines = []
        for row in rubric_breakdown:
            if row.get("score") is not None and float(row["score"]) < 80:
                suggestion_lines.append(f"{row['criterion']}.")
        if suggestion_lines:
            suggestions = "- Add clearer support for:\n\n" + "\n".join(suggestion_lines[:3])
        else:
            suggestions = (
                "- Keep the response structure clear and focused.\n"
                "- Support each claim with concrete examples.\n"
                "- Map each paragraph directly to rubric criteria."
            )
    return {
        "strengths": strengths or "No strengths were explicitly returned by the grader.",
        "areas_for_improvement": improvements,
        "suggestions": suggestions,
    }


def _overall_final_summary(final_grade_row: FinalGrade | None) -> str:
    if not final_grade_row:
        return "Final summary is not available yet."
    parsed = _safe_json_dict(final_grade_row.summary_json)
    text = _first_nonempty_str(
        parsed,
        ("overall_final_summary", "final_summary", "summary", "explanation"),
    )
    if text:
        return text
    if final_grade_row.explanation:
        return final_grade_row.explanation
    return "Final summary is not available yet."


def _points_from_percent(percent: float | int | None, points_possible: float) -> float:
    if percent is None:
        return 0.0
    try:
        pct = float(percent)
    except (TypeError, ValueError):
        pct = 0.0
    pct = max(0.0, min(100.0, pct))
    return round((pct / 100.0) * points_possible, 1)


def _is_sqlite_locked_error(exc: Exception) -> bool:
    return "database is locked" in str(exc).lower()


def _session_hints_used(db: Session, session_id: int) -> int:
    val = (
        db.query(func.coalesce(func.sum(ExamQuestion.hints_used), 0))
        .filter(ExamQuestion.session_id == session_id)
        .scalar()
    )
    return int(val or 0)


def _hint_budget_status(db: Session, session: ExamSession) -> dict[str, int | bool | None]:
    limit = hints_limit_for_strictness(session.grading_strictness)
    used = _session_hints_used(db, session.id)
    remaining = None if limit is None else max(0, limit - used)
    exhausted = False if limit is None else used >= limit
    return {"limit": limit, "used": used, "remaining": remaining, "exhausted": exhausted}


def _looks_prompt_injection(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    red_flags = (
        "ignore previous",
        "disregard previous",
        "ignore all instructions",
        "reveal the answer",
        "just give me the answer",
        "system prompt",
        "bypass",
    )
    return any(flag in t for flag in red_flags)


def _hint_history_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _save_hint_to_history(q: ExamQuestion, hint_text: str) -> None:
    history = _hint_history_list(q.hint_history_json)
    history.append(hint_text)
    q.hint_history_json = json.dumps(history, ensure_ascii=False)
    q.latest_hint = hint_text


def _save_ai_reply_to_history(q: ExamQuestion, reply_text: str) -> None:
    history = _hint_history_list(q.ai_helper_history_json)
    history.append(reply_text)
    q.ai_helper_history_json = json.dumps(history, ensure_ascii=False)
    q.latest_ai_helper_reply = reply_text


def _reply_mentions_question(reply: str, question: str) -> bool:
    r = (reply or "").lower()
    q_words = [w for w in re.findall(r"[a-z0-9']+", (question or "").lower()) if len(w) >= 4]
    if not q_words:
        return True
    return any(w in r for w in q_words[:8])


def _is_clearly_unrelated_exam_ask(question_text: str, context_blob: str) -> bool:
    qt = (question_text or "").strip().lower()
    if not qt:
        return False
    # General coaching asks should stay in-flow even without lexical overlap with
    # prompt context (e.g. "tell me how to approach this question").
    guidance_phrases = (
        "how to approach",
        "how should i approach",
        "approach this question",
        "where should i start",
        "how do i start",
        "what should i focus on",
        "how can i improve",
        "can you guide me",
        "help me understand",
        "explain this question",
        "break this down",
        "next step",
    )
    if any(p in qt for p in guidance_phrases):
        return False

    q_tokens = {
        w
        for w in re.findall(r"[a-z0-9']+", qt)
        if len(w) >= 3
    }
    if not q_tokens:
        return False
    stop_words = {
        "the", "and", "for", "with", "that", "this", "you", "your", "are", "was",
        "from", "have", "what", "when", "where", "which", "how", "why", "can",
        "please", "help", "about", "exam", "question",
    }
    q_tokens = {t for t in q_tokens if t not in stop_words}
    if not q_tokens:
        return False
    ctx_tokens = {
        w
        for w in re.findall(r"[a-z0-9']+", (context_blob or "").lower())
        if len(w) >= 3 and w not in stop_words
    }
    overlap = q_tokens.intersection(ctx_tokens)
    if overlap:
        return False
    # If the student explicitly references exam/question intent, prefer a guided
    # response over outright rejection.
    exam_intent_tokens = {
        "question",
        "prompt",
        "answer",
        "respond",
        "response",
        "rubric",
        "explain",
        "approach",
        "understand",
        "focus",
        "start",
        "write",
    }
    return len(q_tokens.intersection(exam_intent_tokens)) == 0


@app.post("/exam/{session_id}/client-timing")
def exam_client_timing(
    session_id: int,
    client_ms_wall: str = Form(...),
    db: Session = Depends(get_db),
):
    session = db.get(ExamSession, session_id)
    if not session:
        raise HTTPException(404, "Exam not found")
    try:
        ms = float(client_ms_wall)
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid timing value")
    ms = max(0.0, min(ms, 3_600_000.0))
    log_performance_event(
        "client",
        "generate_click_to_first_question_visible",
        ms,
        exam_session_id=session_id,
        meta={
            "description": "Wall-clock ms from Generate first question click until first question page runs in the browser.",
        },
    )
    return Response(status_code=204)


@app.get("/performance-log", response_class=HTMLResponse)
def performance_log(request: Request, db: Session = Depends(get_db)):
    redir = _instructor_login_redirect(request)
    if redir:
        return redir
    rows = (
        db.query(PerformanceLog)
        .order_by(PerformanceLog.id.desc())
        .limit(400)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "performance_log.html",
        {"rows": rows},
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "home.html", {})


@app.get("/start", response_class=HTMLResponse)
def start_exam_choice(request: Request):
    return templates.TemplateResponse(request, "start_choose.html", {})


@app.get("/start/generated", response_class=HTMLResponse)
def start_generated_exam_page(request: Request):
    s = get_settings()
    has_key = bool(str(s.together_api_key or "").strip())
    default_toggle_mock = not has_key or s.mock_llm
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "education_levels": EDUCATION_LEVELS,
            "default_level": DEFAULT_EDUCATION_LEVEL_ID,
            "api_key_configured": has_key,
            "default_toggle_mock": default_toggle_mock,
            "grading_strictness_options": GRADING_STRICTNESS_OPTIONS,
            "default_grading_strictness": DEFAULT_GRADING_STRICTNESS,
        },
    )


@app.get("/start/nominated", response_class=HTMLResponse)
def start_nominated_exam_page(request: Request):
    return templates.TemplateResponse(
        request,
        "start_nominated.html",
        {"error_message": "", "student_id": "", "exam_id": ""},
    )


@app.get("/resume", response_class=HTMLResponse)
def resume_exam_page(request: Request):
    return templates.TemplateResponse(
        request,
        "resume.html",
        {"error_message": "", "student_id": "", "exam_id": ""},
    )


@app.post("/resume", response_class=HTMLResponse)
def resume_exam_submit(
    request: Request,
    student_id: str = Form(""),
    exam_id: str = Form(""),
    db: Session = Depends(get_db),
):
    sid = (student_id or "").strip()
    eid = (exam_id or "").strip().upper()
    if not sid or not eid:
        missing = "student ID and exam ID" if (not sid and not eid) else ("student ID" if not sid else "exam ID")
        return templates.TemplateResponse(
            request,
            "resume.html",
            {
                "error_message": f"Please enter your {missing}.",
                "student_id": sid,
                "exam_id": eid,
            },
            status_code=400,
        )
    session = (
        db.query(ExamSession)
        .join(Student, ExamSession.student_ref_id == Student.id)
        .filter(
            Student.external_student_id == sid,
            ExamSession.exam_code == eid,
            ExamSession.status == "in_progress",
        )
        .one_or_none()
    )
    if not session:
        return templates.TemplateResponse(
            request,
            "resume.html",
            {
                "error_message": "No in-progress exam found for that student ID and exam ID.",
                "student_id": sid,
                "exam_id": eid,
            },
            status_code=404,
        )
    return RedirectResponse(url=f"/exam/{session.id}/question", status_code=303)


@app.post("/exam/start", response_class=HTMLResponse)
def exam_start(
    request: Request,
    student_id: str = Form(...),
    professor_domain: str = Form(...),
    education_level: str = Form(DEFAULT_EDUCATION_LEVEL_ID),
    llm_mode: str = Form("mock"),
    grading_strictness: str = Form(DEFAULT_GRADING_STRICTNESS),
    num_questions: int = Form(1),
    db: Session = Depends(get_db),
):
    student_id = student_id.strip()
    if not student_id:
        raise HTTPException(400, "Student ID required")
    level_key = education_level.strip().lower()
    if level_key not in ALLOWED_LEVEL_IDS:
        raise HTTPException(400, "Invalid education level")
    mode = llm_mode.strip().lower()
    use_mock = mode != "live"
    if not use_mock and not str(get_settings().together_api_key or "").strip():
        raise HTTPException(
            400,
            "Production mode requires TOGETHER_API_KEY in the server .env file.",
        )
    n = max(1, min(20, int(num_questions)))

    gs = grading_strictness.strip().lower()
    if gs not in ALLOWED_STRICTNESS_IDS:
        raise HTTPException(400, "Invalid grading strictness")

    student_row = get_or_create_student(db, student_id)
    session = ExamSession(
        student_ref_id=student_row.id,
        exam_code=generate_unique_exam_code(db),
        professor_domain=professor_domain.strip(),
        education_level=level_key,
        use_mock_llm=use_mock,
        num_questions_planned=n,
        current_question_index=0,
        status="in_progress",
        grading_strictness=gs,
    )
    db.add(session)
    try:
        db.flush()
        payload = generate_question(
            session.professor_domain,
            "",
            question_index=0,
            education_level=session.education_level,
            use_mock=session.use_mock_llm,
            exam_session_id=session.id,
        )
    except TogetherApiError:
        db.rollback()
        raise
    eq = ExamQuestion(
        session_id=session.id,
        question_index=0,
        background_information=payload.get("background_information", ""),
        essay_question=payload.get("essay_question", ""),
        grading_rubric=_rubric_to_stored(payload.get("grading_rubric", [])),
        domain_notes=payload.get("domain_notes"),
    )
    db.add(eq)
    db.commit()

    return RedirectResponse(url=f"/exam/{session.id}/question", status_code=303)


@app.post("/exam/start-nominated", response_class=HTMLResponse)
def exam_start_nominated(
    request: Request,
    student_id: str = Form(""),
    exam_id: str = Form(""),
    db: Session = Depends(get_db),
):
    sid = (student_id or "").strip()
    nom_code = (exam_id or "").strip().upper()
    if not sid or not nom_code:
        missing = "student ID and nominated exam ID" if (not sid and not nom_code) else (
            "student ID" if not sid else "nominated exam ID"
        )
        return templates.TemplateResponse(
            request,
            "start_nominated.html",
            {
                "error_message": f"Please enter your {missing}.",
                "student_id": sid,
                "exam_id": nom_code,
            },
            status_code=400,
        )
    if not _is_valid_nominated_access_code(nom_code):
        return templates.TemplateResponse(
            request,
            "start_nominated.html",
            {
                "error_message": "Nominated exam ID must be exactly 8 letters or digits (from your instructor).",
                "student_id": sid,
                "exam_id": nom_code,
            },
            status_code=400,
        )
    tpl = db.query(NominatedExam).filter(NominatedExam.access_code == nom_code).one_or_none()
    if not tpl:
        return templates.TemplateResponse(
            request,
            "start_nominated.html",
            {
                "error_message": "No nominated exam was found for that exam ID.",
                "student_id": sid,
                "exam_id": nom_code,
            },
            status_code=404,
        )
    snaps = (
        db.query(NominatedExamSnapshotQuestion)
        .filter(NominatedExamSnapshotQuestion.nominated_exam_id == tpl.id)
        .order_by(NominatedExamSnapshotQuestion.question_index.asc())
        .all()
    )
    if not snaps:
        return templates.TemplateResponse(
            request,
            "start_nominated.html",
            {
                "error_message": "That nominated exam has no questions yet. Ask your instructor to republish it.",
                "student_id": sid,
                "exam_id": nom_code,
            },
            status_code=404,
        )
    student_row = get_or_create_student(db, sid)
    n = len(snaps)
    session = ExamSession(
        student_ref_id=student_row.id,
        exam_code=generate_unique_exam_code(db),
        professor_domain=tpl.professor_domain,
        education_level=tpl.education_level,
        use_mock_llm=tpl.use_mock_llm,
        num_questions_planned=n,
        current_question_index=0,
        status="in_progress",
        grading_strictness=tpl.grading_strictness,
        nominated_exam_template_id=tpl.id,
    )
    db.add(session)
    db.flush()
    for snap in snaps:
        merged = _merge_instructor_note_into_domain_notes(snap.domain_notes, snap.instructor_note)
        db.add(
            ExamQuestion(
                session_id=session.id,
                question_index=snap.question_index,
                background_information=snap.background_information,
                essay_question=snap.essay_question,
                grading_rubric=snap.grading_rubric,
                domain_notes=merged,
            )
        )
    db.commit()
    return RedirectResponse(url=f"/exam/{session.id}/question", status_code=303)


@app.get("/exam/{session_id}/question", response_class=HTMLResponse)
def exam_question(request: Request, session_id: int, db: Session = Depends(get_db)):
    session = db.get(ExamSession, session_id)
    if not session:
        raise HTTPException(404, "Exam not found")
    if session.status != "in_progress":
        return RedirectResponse(url=f"/exam/{session_id}/results", status_code=303)

    idx = session.current_question_index
    q = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.session_id == session.id, ExamQuestion.question_index == idx)
        .one_or_none()
    )
    if not q:
        raise HTTPException(404, "Question not found")

    rubric_display = q.grading_rubric
    try:
        rubric_display = json.loads(q.grading_rubric)
        if isinstance(rubric_display, list):
            rubric_display = rubric_display
        else:
            rubric_display = q.grading_rubric
    except json.JSONDecodeError:
        rubric_display = q.grading_rubric

    hint_state = _hint_budget_status(db, session)
    hint_history = _hint_history_list(q.hint_history_json)
    ai_helper_history = _hint_history_list(q.ai_helper_history_json)
    return templates.TemplateResponse(
        request,
        "question.html",
        {
            "session": session,
            "question": q,
            "question_number": idx + 1,
            "total_planned": session.num_questions_planned,
            "rubric_display": rubric_display,
            "education_label": label_for_level(session.education_level),
            "llm_mode_label": "Mock" if session.use_mock_llm else "Production",
            "grading_label": label_for_strictness(session.grading_strictness),
            "hint_limit": hint_state["limit"],
            "hint_used": hint_state["used"],
            "hint_remaining": hint_state["remaining"],
            "hint_exhausted": hint_state["exhausted"],
            "latest_hint": q.latest_hint,
            "hint_history": hint_history,
            "ai_helper_history": ai_helper_history,
        },
    )


@app.post("/exam/{session_id}/hint", response_class=HTMLResponse)
def exam_hint(
    request: Request,
    session_id: int,
    answer_draft: str = Form(""),
    db: Session = Depends(get_db),
):
    session = db.get(ExamSession, session_id)
    if not session:
        raise HTTPException(404, "Exam not found")
    if session.status != "in_progress":
        return RedirectResponse(url=f"/exam/{session_id}/results", status_code=303)

    idx = session.current_question_index
    q = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.session_id == session.id, ExamQuestion.question_index == idx)
        .one_or_none()
    )
    if not q:
        raise HTTPException(404, "Question not found")

    hint_state = _hint_budget_status(db, session)
    if hint_state["exhausted"]:
        q.latest_hint = "No hints remaining for your selected grading strictness."
        db.add(q)
        db.commit()
        return RedirectResponse(url=f"/exam/{session_id}/question", status_code=303)

    student_text = (answer_draft or "").strip()
    if _looks_prompt_injection(student_text):
        q.latest_hint = AI_HELPER_OFFTOPIC_MESSAGE
        q.hints_used = int(q.hints_used or 0) + 1
        db.add(q)
        db.commit()
        return RedirectResponse(url=f"/exam/{session_id}/question", status_code=303)

    try:
        if mode_key == "chat":
            hint_payload = generate_ai_helper_reply(
                essay_question=q.essay_question,
                background_information=q.background_information,
                selected_hint=selected_hint_text,
                student_question=query_text,
                education_level=session.education_level,
                use_mock=session.use_mock_llm,
                exam_session_id=session.id,
            )
        else:
            hint_payload = generate_safe_hint(
                essay_question=q.essay_question,
                background_information=q.background_information,
                grading_rubric=q.grading_rubric,
                student_text=student_text or q.essay_question,
                education_level=session.education_level,
                use_mock=session.use_mock_llm,
                exam_session_id=session.id,
            )
    except TogetherApiError:
        db.rollback()
        raise

    hint_status = str(hint_payload.get("status", "ok")).strip().lower()
    reply_key = "reply" if mode_key == "chat" else "hint"
    hint_text = str(hint_payload.get(reply_key, "")).strip()
    if hint_status == "irrelevant":
        hint_text = AI_HELPER_OFFTOPIC_MESSAGE
    if not hint_text:
        hint_text = "Focus on the key terms in the question, then explain one concept in your own words first."
    q.latest_hint = hint_text[:1000]
    q.hints_used = int(q.hints_used or 0) + 1
    db.add(q)
    db.commit()
    return RedirectResponse(url=f"/exam/{session_id}/question", status_code=303)


@app.post("/exam/{session_id}/hint-json")
def exam_hint_json(
    session_id: int,
    answer_draft: str = Form(""),
    hint_query: str = Form(""),
    selected_hint: str = Form(""),
    mode: str = Form("hint"),
    db: Session = Depends(get_db),
):
    session = db.get(ExamSession, session_id)
    if not session:
        raise HTTPException(404, "Exam not found")
    if session.status != "in_progress":
        raise HTTPException(400, "Exam is not active")

    idx = session.current_question_index
    q = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.session_id == session.id, ExamQuestion.question_index == idx)
        .one_or_none()
    )
    if not q:
        raise HTTPException(404, "Question not found")

    hint_state = _hint_budget_status(db, session)
    existing_history = _hint_history_list(q.hint_history_json)
    existing_ai_history = _hint_history_list(q.ai_helper_history_json)
    mode_key = (mode or "hint").strip().lower()
    if mode_key == "hint" and hint_state["exhausted"]:
        return JSONResponse(
            {
                "ok": False,
                "hint": "No hints remaining for your selected grading strictness.",
                "hint_used": int(hint_state["used"]),
                "hint_limit": hint_state["limit"],
                "hint_remaining": hint_state["remaining"],
                "hint_exhausted": True,
                "hint_history": existing_history,
                "ai_helper_history": existing_ai_history,
                "mode": mode_key,
            },
            status_code=200,
        )
    if mode_key == "chat" and hint_state["exhausted"]:
        return JSONResponse(
            {
                "ok": False,
                "hint": AI_HELPER_NO_HINTS_MESSAGE,
                "hint_used": int(hint_state["used"]),
                "hint_limit": hint_state["limit"],
                "hint_remaining": hint_state["remaining"],
                "hint_exhausted": True,
                "hint_history": existing_history,
                "ai_helper_history": existing_ai_history,
                "mode": mode_key,
            },
            status_code=200,
        )

    query_text = (hint_query or "").strip()
    query_words = query_text.split()
    if len(query_words) > 100:
        return JSONResponse(
            {
                "ok": False,
                "hint": "Please keep hint questions to 100 words or fewer.",
                "hint_used": int(hint_state["used"]),
                "hint_limit": hint_state["limit"],
                "hint_remaining": hint_state["remaining"],
                "hint_exhausted": False,
                "hint_history": existing_history,
                "ai_helper_history": existing_ai_history,
                "mode": mode_key,
            },
            status_code=200,
        )

    selected_hint_text = (selected_hint or "").strip()
    if mode_key == "chat" and query_text:
        context_blob = " ".join(
            part
            for part in (
                q.essay_question or "",
                q.background_information or "",
                q.grading_rubric or "",
                selected_hint_text or "",
            )
            if part
        )
        if _is_clearly_unrelated_exam_ask(query_text, context_blob):
            response_text = AI_HELPER_OFFTOPIC_MESSAGE
            _save_ai_reply_to_history(q, response_text)
            db.add(q)
            db.commit()
            after = _hint_budget_status(db, session)
            updated_history = _hint_history_list(q.hint_history_json)
            updated_ai_history = _hint_history_list(q.ai_helper_history_json)
            return JSONResponse(
                {
                    "ok": True,
                    "hint": response_text,
                    "hint_used": int(after["used"]),
                    "hint_limit": after["limit"],
                    "hint_remaining": after["remaining"],
                    "hint_exhausted": bool(after["exhausted"]),
                    "hint_history": updated_history,
                    "ai_helper_history": updated_ai_history,
                    "mode": mode_key,
                }
            )

    student_text = " ".join(
        part for part in ((answer_draft or "").strip(), selected_hint_text, query_text) if part
    )
    if _looks_prompt_injection(student_text):
        response_text = AI_HELPER_OFFTOPIC_MESSAGE
        if mode_key == "chat":
            _save_ai_reply_to_history(q, response_text)
        else:
            _save_hint_to_history(q, response_text)
            q.hints_used = int(q.hints_used or 0) + 1
        db.add(q)
        db.commit()
        after = _hint_budget_status(db, session)
        updated_history = _hint_history_list(q.hint_history_json)
        updated_ai_history = _hint_history_list(q.ai_helper_history_json)
        return JSONResponse(
            {
                "ok": True,
                "hint": response_text,
                "hint_used": int(after["used"]),
                "hint_limit": after["limit"],
                "hint_remaining": after["remaining"],
                "hint_exhausted": bool(after["exhausted"]),
                "hint_history": updated_history,
                "ai_helper_history": updated_ai_history,
                "mode": mode_key,
            }
        )

    try:
        hint_payload = generate_safe_hint(
            essay_question=q.essay_question,
            background_information=q.background_information,
            grading_rubric=q.grading_rubric,
            student_text=student_text or q.essay_question,
            education_level=session.education_level,
            use_mock=session.use_mock_llm,
            exam_session_id=session.id,
        )
    except TogetherApiError:
        db.rollback()
        raise

    hint_status = str(hint_payload.get("status", "ok")).strip().lower()
    hint_text = str(hint_payload.get("hint", "")).strip()
    if hint_status == "irrelevant":
        hint_text = AI_HELPER_OFFTOPIC_MESSAGE
    if not hint_text:
        hint_text = "Focus on the key terms in the question, then explain one concept in your own words first."
    safe_text = hint_text[:1000]
    if mode_key == "chat" and query_text and not _reply_mentions_question(safe_text, query_text):
        safe_text = f"About your question \"{query_text[:140]}\": {safe_text}"
    if mode_key == "chat":
        _save_ai_reply_to_history(q, safe_text)
        # Do not charge hint budget when the helper can only return the
        # generic redirect/off-topic fallback.
        if safe_text != AI_HELPER_OFFTOPIC_MESSAGE:
            q.hints_used = int(q.hints_used or 0) + 1
    else:
        _save_hint_to_history(q, safe_text)
        q.hints_used = int(q.hints_used or 0) + 1
    db.add(q)
    db.commit()
    after = _hint_budget_status(db, session)
    updated_history = _hint_history_list(q.hint_history_json)
    updated_ai_history = _hint_history_list(q.ai_helper_history_json)
    return JSONResponse(
        {
            "ok": True,
            "hint": safe_text,
            "hint_used": int(after["used"]),
            "hint_limit": after["limit"],
            "hint_remaining": after["remaining"],
            "hint_exhausted": bool(after["exhausted"]),
            "hint_history": updated_history,
            "ai_helper_history": updated_ai_history,
            "mode": mode_key,
        }
    )


@app.post("/exam/{session_id}/answer", response_class=HTMLResponse)
def exam_answer(
    request: Request,
    session_id: int,
    answer: str = Form(...),
    db: Session = Depends(get_db),
):
    session = db.get(ExamSession, session_id)
    if not session:
        raise HTTPException(404, "Exam not found")
    # Idempotent: duplicate POST after exam is finished → send user to results (no error).
    if session.status == "completed":
        return RedirectResponse(url=f"/exam/{session_id}/results", status_code=303)
    if session.status != "in_progress":
        raise HTTPException(400, "Invalid session")

    idx = session.current_question_index
    q = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.session_id == session.id, ExamQuestion.question_index == idx)
        .one_or_none()
    )
    if not q:
        raise HTTPException(404, "Question not found")

    sec = None

    q.student_response = answer.strip()
    q.seconds_on_question = sec

    next_index = idx + 1

    if next_index < session.num_questions_planned:
        existing_next = (
            db.query(ExamQuestion)
            .filter(
                ExamQuestion.session_id == session.id,
                ExamQuestion.question_index == next_index,
            )
            .one_or_none()
        )
        if existing_next and q.graded_state_p_json:
            db.refresh(session)
            if session.current_question_index != next_index:
                session.current_question_index = next_index
                db.add(session)
                db.commit()
            return RedirectResponse(url=f"/exam/{session_id}/question", status_code=303)

        if not existing_next:
            try:
                db.flush()
            except OperationalError as exc:
                db.rollback()
                if _is_sqlite_locked_error(exc):
                    return RedirectResponse(url=f"/exam/{session_id}/question", status_code=303)
                raise

            try:
                prior = _prior_summary(session, db)
                grade_payload, payload = grade_and_next_question_combined(
                    session.professor_domain,
                    prior,
                    next_question_index=next_index,
                    background_information=q.background_information,
                    essay_question=q.essay_question,
                    grading_rubric=q.grading_rubric,
                    student_response=q.student_response,
                    seconds_on_question=sec,
                    education_level=session.education_level,
                    grading_strictness=session.grading_strictness,
                    use_mock=session.use_mock_llm,
                    exam_session_id=session.id,
                )
            except TogetherApiError:
                db.rollback()
                raise
            q.graded_state_p_json = json.dumps(grade_payload, ensure_ascii=False)
            db.add(q)
            nq = ExamQuestion(
                session_id=session.id,
                question_index=next_index,
                background_information=payload.get("background_information", ""),
                essay_question=payload.get("essay_question", ""),
                grading_rubric=_rubric_to_stored(payload.get("grading_rubric", [])),
                domain_notes=payload.get("domain_notes"),
            )
            db.add(nq)
            session.current_question_index = next_index
            db.add(session)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                return RedirectResponse(url=f"/exam/{session_id}/question", status_code=303)
            except OperationalError as exc:
                db.rollback()
                if _is_sqlite_locked_error(exc):
                    return RedirectResponse(url=f"/exam/{session_id}/question", status_code=303)
                raise
            return RedirectResponse(url=f"/exam/{session_id}/question", status_code=303)

        try:
            db.flush()
        except OperationalError as exc:
            db.rollback()
            if _is_sqlite_locked_error(exc):
                return RedirectResponse(url=f"/exam/{session_id}/question", status_code=303)
            raise

        try:
            grade_payload = grade_answer(
                q.background_information,
                q.essay_question,
                q.grading_rubric,
                q.student_response,
                sec,
                education_level=session.education_level,
                grading_strictness=session.grading_strictness,
                use_mock=session.use_mock_llm,
                exam_session_id=session.id,
            )
        except TogetherApiError:
            db.rollback()
            raise
        q.graded_state_p_json = json.dumps(grade_payload, ensure_ascii=False)
        db.add(q)
        session.current_question_index = next_index
        db.add(session)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return RedirectResponse(url=f"/exam/{session_id}/question", status_code=303)
        except OperationalError as exc:
            db.rollback()
            if _is_sqlite_locked_error(exc):
                return RedirectResponse(url=f"/exam/{session_id}/question", status_code=303)
            raise
        return RedirectResponse(url=f"/exam/{session_id}/question", status_code=303)

    # Last question: one API call for this answer’s grade + overall final grade (was two calls)
    existing_fg = (
        db.query(FinalGrade).filter(FinalGrade.session_id == session.id).one_or_none()
    )
    if existing_fg:
        session.status = "completed"
        session.final_grade_json = existing_fg.summary_json
        db.add(session)
        db.commit()
        return RedirectResponse(url=f"/exam/{session_id}/results", status_code=303)

    try:
        db.flush()
    except OperationalError as exc:
        db.rollback()
        if _is_sqlite_locked_error(exc):
            return RedirectResponse(url=f"/exam/{session_id}/question", status_code=303)
        raise
    earlier = _earlier_graded_blob(db, session, idx)
    try:
        grade_payload, final_payload = grade_and_final_combined(
            earlier,
            q.background_information,
            q.essay_question,
            q.grading_rubric,
            q.student_response,
            sec,
            education_level=session.education_level,
            grading_strictness=session.grading_strictness,
            use_mock=session.use_mock_llm,
            exam_session_id=session.id,
        )
    except TogetherApiError:
        db.rollback()
        raise
    q.graded_state_p_json = json.dumps(grade_payload, ensure_ascii=False)
    db.add(q)
    fg = FinalGrade(
        session_id=session.id,
        total_grade_percent=float(final_payload.get("total_grade_percent", 0)),
        explanation=final_payload.get("explanation", ""),
        summary_json=json.dumps(final_payload, ensure_ascii=False),
    )
    db.add(fg)
    session.status = "completed"
    session.final_grade_json = fg.summary_json
    db.add(session)
    try:
        db.commit()
    except IntegrityError:
        # Concurrent last answer: another request inserted final_grades first.
        db.rollback()
        if db.query(FinalGrade).filter(FinalGrade.session_id == session_id).one_or_none():
            return RedirectResponse(url=f"/exam/{session_id}/results", status_code=303)
        raise
    except OperationalError as exc:
        db.rollback()
        if _is_sqlite_locked_error(exc):
            if db.query(FinalGrade).filter(FinalGrade.session_id == session_id).one_or_none():
                return RedirectResponse(url=f"/exam/{session_id}/results", status_code=303)
            return RedirectResponse(url=f"/exam/{session_id}/question", status_code=303)
        raise

    return RedirectResponse(url=f"/exam/{session_id}/results", status_code=303)


@app.get("/exam/{session_id}/results", response_class=HTMLResponse)
def exam_results(request: Request, session_id: int, db: Session = Depends(get_db)):
    session = db.get(ExamSession, session_id)
    if not session:
        raise HTTPException(404, "Exam not found")
    rows = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.session_id == session.id)
        .order_by(ExamQuestion.question_index.asc())
        .all()
    )
    fg = db.query(FinalGrade).filter(FinalGrade.session_id == session.id).one_or_none()
    total_points_possible = round(max(1, session.num_questions_planned) * POINTS_PER_QUESTION, 1)
    overall_points_earned = _points_from_percent(
        fg.total_grade_percent if fg else 0.0, total_points_possible
    )
    result_items = []
    for q in rows:
        grade_payload = _safe_json_dict(q.graded_state_p_json)
        rubric = _rubric_items(q.grading_rubric)
        dimension_scores = grade_payload.get("dimension_scores", {})
        rubric_breakdown = []
        for idx, criterion in enumerate(rubric):
            label, score = _best_dimension_match(dimension_scores, criterion, idx)
            rubric_breakdown.append(
                {
                    "criterion": criterion,
                    "dimension_label": label,
                    "score": score,
                }
            )
        result_items.append(
            {
                "question": q,
                "grade": grade_payload,
                "rubric": rubric,
                "rubric_breakdown": rubric_breakdown,
                "reference_answer": _reference_answer_text(grade_payload, rubric),
                "rubric_feedback": _rubric_feedback_sections(
                    grade_payload, rubric_breakdown, rubric
                ),
                "points_earned": _points_from_percent(
                    grade_payload.get("overall_percent"), POINTS_PER_QUESTION
                ),
                "points_possible": POINTS_PER_QUESTION,
            }
        )
    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "session": session,
            "questions": rows,
            "result_items": result_items,
            "final_grade": fg,
            "overall_final_summary": _overall_final_summary(fg),
            "overall_points_earned": overall_points_earned,
            "overall_points_possible": total_points_possible,
            "education_label": label_for_level(session.education_level),
            "llm_mode_label": "Mock" if session.use_mock_llm else "Production",
            "grading_label": label_for_strictness(session.grading_strictness),
        },
    )


@app.get("/professor/login", response_class=HTMLResponse)
def professor_login_get(
    request: Request, next_url: str = Query(default="/professor", alias="next")
):
    if instructor_session_ok(request):
        return RedirectResponse(url=_safe_instructor_next_url(next_url), status_code=303)
    return templates.TemplateResponse(
        request,
        "professor_login.html",
        {"next": _safe_instructor_next_url(next_url)},
    )


@app.post("/professor/login", response_class=HTMLResponse)
def professor_login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next_url: str = Form(default="/professor", alias="next"),
):
    safe_next = _safe_instructor_next_url(next_url)
    try:
        settings = get_settings()
        if verify_instructor_login(username.strip(), password, BASE_DIR, settings):
            request.session[SESSION_KEY] = True
            return RedirectResponse(url=safe_next, status_code=303)
    except Exception:
        logger.exception("Professor login POST failed")
        return templates.TemplateResponse(
            request,
            "professor_login.html",
            {
                "error": "Could not complete sign-in. Try again, or check instructor_credentials.json and server logs.",
                "next": safe_next,
            },
            status_code=403,
        )
    # Use 403 (not 401) so browsers and password managers do not treat this as HTTP
    # "WWW-Authenticate" auth, which can cause odd follow-up requests or error pages.
    return templates.TemplateResponse(
        request,
        "professor_login.html",
        {
            "error": "Invalid username or password.",
            "next": safe_next,
        },
        status_code=403,
    )


@app.post("/professor/logout")
def professor_logout(request: Request):
    request.session.pop(SESSION_KEY, None)
    return RedirectResponse(url="/professor/login", status_code=303)


@app.get("/professor", response_class=HTMLResponse)
def professor_dashboard(request: Request, db: Session = Depends(get_db)):
    redir = _instructor_login_redirect(request)
    if redir:
        return redir
    sessions = db.query(ExamSession).order_by(ExamSession.created_at.desc()).limit(200).all()
    return templates.TemplateResponse(request, "professor.html", {"sessions": sessions})


@app.get("/professor/tools", response_class=HTMLResponse)
def professor_developer_tools(request: Request):
    redir = _instructor_login_redirect(request)
    if redir:
        return redir
    return templates.TemplateResponse(request, "professor_tools.html", {})


def _safe_question_analysis_redirect(next_raw: str | None) -> str:
    default = "/professor/question-analysis"
    if not next_raw:
        return default
    n = str(next_raw).strip()
    if "://" in n or n.startswith("//"):
        return default
    u = urlparse(n)
    if u.netloc:
        return default
    path = (u.path or "").rstrip("/") or "/"
    allowed_paths = frozenset(
        {
            "/professor/question-analysis",
            "/professor/question-analysis/nomination",
            "/professor/question-analysis/manual-feedback",
        }
    )
    if path not in allowed_paths:
        return default
    return n


@app.post("/professor/question-analysis/feedback")
def professor_question_analysis_feedback(
    request: Request,
    db: Session = Depends(get_db),
    session_id: int = Form(),
    question_id: int = Form(),
    instructor_note: str = Form(""),
    next: str = Form("/professor/question-analysis"),
):
    redir = _instructor_login_redirect(request)
    if redir:
        return redir
    note = (instructor_note or "").strip()[:20000]
    row = (
        db.query(QuestionAnalysisFeedback)
        .filter(
            QuestionAnalysisFeedback.session_id == int(session_id),
            QuestionAnalysisFeedback.question_id == int(question_id),
        )
        .one_or_none()
    )
    if row:
        row.instructor_note = note
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(
            QuestionAnalysisFeedback(
                session_id=int(session_id),
                question_id=int(question_id),
                instructor_note=note,
            )
        )
    db.commit()
    return RedirectResponse(_safe_question_analysis_redirect(next), status_code=303)


@app.post("/professor/question-analysis/create-nominated-exam")
async def professor_create_nominated_exam(request: Request, db: Session = Depends(get_db)):
    redir = _instructor_login_redirect(request)
    if redir:
        return redir
    form = await request.form()
    title = str(form.get("title") or "").strip()[:512]
    next_raw = str(form.get("next") or "/professor/question-analysis/nomination")
    dest = _safe_question_analysis_redirect(next_raw)
    raw_ids = form.getlist("question_id")
    qids: list[int] = []
    for x in raw_ids:
        s = str(x).strip()
        if s.isdigit():
            qids.append(int(s))
    qids = list(dict.fromkeys(qids))
    if not qids:
        return RedirectResponse(f"{dest}?nominated_error=no_questions", status_code=303)

    rows = (
        db.query(ExamQuestion, ExamSession)
        .join(ExamSession, ExamQuestion.session_id == ExamSession.id)
        .filter(ExamQuestion.id.in_(qids))
        .all()
    )
    if len(rows) != len(qids):
        return RedirectResponse(f"{dest}?nominated_error=invalid_questions", status_code=303)
    session_ids = {s.id for (_, s) in rows}
    if len(session_ids) != 1:
        return RedirectResponse(f"{dest}?nominated_error=mixed_sessions", status_code=303)

    pairs_sorted = sorted(rows, key=lambda p: (p[0].question_index, p[0].id))
    _, source_sess = pairs_sorted[0]

    fb_rows = (
        db.query(QuestionAnalysisFeedback)
        .filter(QuestionAnalysisFeedback.question_id.in_(qids))
        .all()
    )
    fb_by_qid = {r.question_id: (r.instructor_note or "") for r in fb_rows}

    access_code = generate_unique_nominated_access_code(db)
    tpl = NominatedExam(
        access_code=access_code,
        title=title,
        source_session_id=source_sess.id,
        professor_domain=source_sess.professor_domain,
        education_level=source_sess.education_level,
        use_mock_llm=bool(source_sess.use_mock_llm),
        grading_strictness=source_sess.grading_strictness,
    )
    db.add(tpl)
    db.flush()

    for new_index, (eq, _) in enumerate(pairs_sorted):
        note = fb_by_qid.get(eq.id, "")
        db.add(
            NominatedExamSnapshotQuestion(
                nominated_exam_id=tpl.id,
                source_question_id=eq.id,
                question_index=new_index,
                background_information=eq.background_information or "",
                essay_question=eq.essay_question or "",
                grading_rubric=eq.grading_rubric or "",
                domain_notes=eq.domain_notes,
                instructor_note=note,
            )
        )
    db.commit()
    sep = "&" if "?" in dest else "?"
    return RedirectResponse(f"{dest}{sep}nominated_created={access_code}", status_code=303)


@app.get("/professor/question-analysis/nomination", response_class=HTMLResponse)
async def professor_question_analysis_nomination(
    request: Request,
    db: Session = Depends(get_db),
    session_id_raw: str | None = Query(default=None, alias="session_id"),
    education_level: str | None = Query(default=None),
    llm_mode: str = Query(default="all"),
    compare_by: str = Query(default="education_level"),
    run: str = Query(default="1"),
    sample_limit: int = Query(default=200, ge=1, le=2000),
    nominated_created: str | None = Query(default=None),
    nominated_error: str | None = Query(default=None),
):
    redir = _instructor_login_redirect(request)
    if redir:
        return redir
    state = normalize_question_analysis_params(
        session_id_raw=session_id_raw,
        education_level=education_level,
        llm_mode=llm_mode,
        compare_by=compare_by,
        run=run,
        sample_limit=sample_limit,
    )
    ctx = await load_question_analysis_context(db, state=state)
    ctx["nominated_created"] = (nominated_created or "").strip().upper()[:16]
    ctx["nominated_error"] = (nominated_error or "").strip()
    return templates.TemplateResponse(request, "question_analysis_nomination.html", ctx)


@app.get("/professor/question-analysis/manual-feedback", response_class=HTMLResponse)
async def professor_question_analysis_manual_feedback(
    request: Request,
    db: Session = Depends(get_db),
    session_id_raw: str | None = Query(default=None, alias="session_id"),
    education_level: str | None = Query(default=None),
    llm_mode: str = Query(default="all"),
    compare_by: str = Query(default="education_level"),
    run: str = Query(default="1"),
    sample_limit: int = Query(default=200, ge=1, le=2000),
):
    redir = _instructor_login_redirect(request)
    if redir:
        return redir
    state = normalize_question_analysis_params(
        session_id_raw=session_id_raw,
        education_level=education_level,
        llm_mode=llm_mode,
        compare_by=compare_by,
        run=run,
        sample_limit=sample_limit,
    )
    ctx = await load_question_analysis_context(db, state=state)
    return templates.TemplateResponse(request, "question_analysis_manual_feedback.html", ctx)


@app.get("/professor/question-analysis", response_class=HTMLResponse)
async def professor_question_analysis(
    request: Request,
    db: Session = Depends(get_db),
    session_id_raw: str | None = Query(default=None, alias="session_id"),
    education_level: str | None = Query(default=None),
    llm_mode: str = Query(default="all"),
    compare_by: str = Query(default="education_level"),
    run: str = Query(default="0"),
    sample_limit: int = Query(default=200, ge=1, le=2000),
):
    redir = _instructor_login_redirect(request)
    if redir:
        return redir
    state = normalize_question_analysis_params(
        session_id_raw=session_id_raw,
        education_level=education_level,
        llm_mode=llm_mode,
        compare_by=compare_by,
        run=run,
        sample_limit=sample_limit,
    )
    ctx = await load_question_analysis_context(db, state=state)
    return templates.TemplateResponse(request, "question_analysis.html", ctx)


@app.get("/professor/exam/{session_id}", response_class=HTMLResponse)
def professor_exam_detail(request: Request, session_id: int, db: Session = Depends(get_db)):
    redir = _instructor_login_redirect(request)
    if redir:
        return redir
    session = db.get(ExamSession, session_id)
    if not session:
        raise HTTPException(404, "Not found")
    rows = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.session_id == session.id)
        .order_by(ExamQuestion.question_index.asc())
        .all()
    )
    fg = db.query(FinalGrade).filter(FinalGrade.session_id == session.id).one_or_none()
    total_points_possible = round(max(1, session.num_questions_planned) * POINTS_PER_QUESTION, 1)
    overall_points_earned = _points_from_percent(
        fg.total_grade_percent if fg else 0.0, total_points_possible
    )
    graded = []
    for r in rows:
        gp = _safe_json_dict(r.graded_state_p_json)
        rubric = _rubric_items(r.grading_rubric)
        dimension_scores = gp.get("dimension_scores", {})
        rubric_breakdown = []
        for idx, criterion in enumerate(rubric):
            label, score = _best_dimension_match(dimension_scores, criterion, idx)
            rubric_breakdown.append(
                {
                    "criterion": criterion,
                    "dimension_label": label,
                    "score": score,
                }
            )
        graded.append(
            {
                "row": r,
                "grade": gp,
                "rubric": rubric,
                "rubric_breakdown": rubric_breakdown,
                "reference_answer": _reference_answer_text(gp, rubric),
                "rubric_feedback": _rubric_feedback_sections(gp, rubric_breakdown, rubric),
                "points_earned": _points_from_percent(
                    gp.get("overall_percent"), POINTS_PER_QUESTION
                ),
                "points_possible": POINTS_PER_QUESTION,
            }
        )
    return templates.TemplateResponse(
        request,
        "professor_detail.html",
        {
            "session": session,
            "items": graded,
            "final_grade": fg,
            "overall_final_summary": _overall_final_summary(fg),
            "overall_points_earned": overall_points_earned,
            "overall_points_possible": total_points_possible,
            "grading_label": label_for_strictness(session.grading_strictness),
        },
    )
