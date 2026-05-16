"""Shared loading and URL helpers for instructor question-analysis pages."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.analysis_agent_client import analyze_questions_via_agent
from app.config import get_settings
from app.database import ExamQuestion, ExamSession, NominatedExam, QuestionAnalysisFeedback
from app.education_levels import ALLOWED_LEVEL_IDS, EDUCATION_LEVELS
from app.question_analysis import (
    ANALYSIS_COMPARE_BY_HELP,
    ANALYSIS_LLM_FILTER_HELP,
    analysis_dataframe,
    analyze_questions_semantic,
    build_analysis_chart_payload,
    summarize_by_category,
)


COMPARE_OPTIONS: dict[str, str] = {
    "education_level": "Education level",
    "llm_mode": "LLM mode",
    "session_id": "Session",
    "quality_code": "Quality code (1–4)",
    "grade_appropriateness_code": "Appropriateness code (1–4)",
}


@dataclass(frozen=True)
class QuestionAnalysisFilterState:
    session_id: int | None
    education_level: str
    llm_mode: str
    compare_by: str
    sample_limit: int
    run_analysis: bool


def normalize_question_analysis_params(
    *,
    session_id_raw: str | None,
    education_level: str | None,
    llm_mode: str,
    compare_by: str,
    run: str,
    sample_limit: int,
) -> QuestionAnalysisFilterState:
    session_id: int | None = None
    if session_id_raw and str(session_id_raw).strip().isdigit():
        session_id = int(str(session_id_raw).strip())

    lev = (education_level or "").strip()
    if lev and lev not in ALLOWED_LEVEL_IDS:
        lev = ""
    lm = (llm_mode or "all").strip().lower()
    if lm not in ("all", "mock", "production"):
        lm = "all"
    compare_key = (compare_by or "education_level").strip().lower()
    if compare_key not in COMPARE_OPTIONS:
        compare_key = "education_level"
    should_run = (run or "").strip().lower() in ("1", "true", "yes", "on")
    return QuestionAnalysisFilterState(
        session_id=session_id,
        education_level=lev,
        llm_mode=lm,
        compare_by=compare_key,
        sample_limit=sample_limit,
        run_analysis=should_run,
    )


def filter_query_string(state: QuestionAnalysisFilterState, *, run: str | None = None) -> str:
    """Rebuild GET query for question-analysis family URLs."""
    params: dict[str, Any] = {}
    if state.session_id is not None:
        params["session_id"] = state.session_id
    if state.education_level:
        params["education_level"] = state.education_level
    params["llm_mode"] = state.llm_mode
    params["compare_by"] = state.compare_by
    params["sample_limit"] = state.sample_limit
    params["run"] = run if run is not None else ("1" if state.run_analysis else "0")
    return urlencode(params)


async def load_question_analysis_context(
    db: Session,
    *,
    state: QuestionAnalysisFilterState,
) -> dict[str, Any]:
    """DB + scoring pipeline shared by main analysis, nomination, and manual-feedback pages."""
    q = db.query(ExamQuestion, ExamSession).join(ExamSession, ExamQuestion.session_id == ExamSession.id)
    if state.session_id is not None:
        q = q.filter(ExamSession.id == int(state.session_id))
    if state.education_level:
        q = q.filter(ExamSession.education_level == state.education_level)
    if state.llm_mode == "mock":
        q = q.filter(ExamSession.use_mock_llm.is_(True))
    elif state.llm_mode == "production":
        q = q.filter(ExamSession.use_mock_llm.is_(False))

    pairs = (
        q.order_by(ExamSession.id.desc(), ExamQuestion.question_index.asc())
        .limit(2500)
        .all()
    )
    row_dicts = [
        {
            "session_id": session.id,
            "exam_code": session.exam_code,
            "question_id": eq.id,
            "question_index": eq.question_index,
            "education_level": session.education_level,
            "use_mock_llm": session.use_mock_llm,
            "essay_question": eq.essay_question,
            "professor_domain": session.professor_domain,
            "background_information": eq.background_information or "",
        }
        for (eq, session) in pairs
    ]

    error_message: str | None = None
    analysis_rows: list[Any] = []
    methodology_note = ""
    chart_payload: dict[str, Any] | None = None
    category_table = None
    recent_sessions = (
        db.query(ExamSession).order_by(ExamSession.created_at.desc()).limit(80).all()
    )
    uses_remote_agent = bool((get_settings().analysis_agent_base_url or "").strip())

    if state.run_analysis:
        try:
            lim = state.sample_limit if state.sample_limit else None
            if uses_remote_agent and row_dicts:
                analysis_rows, methodology_note = await analyze_questions_via_agent(
                    row_dicts,
                    sample_limit=lim,
                    model_name=get_settings().question_analysis_st_model,
                )
            elif uses_remote_agent and not row_dicts:
                analysis_rows = []
                methodology_note = "No questions matched the filters."
            else:

                def _local_run():
                    return analyze_questions_semantic(
                        row_dicts,
                        model_name=get_settings().question_analysis_st_model,
                        sample_limit=lim,
                    )

                analysis_rows, methodology_note = await asyncio.to_thread(_local_run)
            df = analysis_dataframe(analysis_rows)
            category_table = (
                summarize_by_category(df, compare_by=state.compare_by) if not df.empty else None
            )
            chart_payload = build_analysis_chart_payload(df, compare_by=state.compare_by)
        except RuntimeError as e:
            error_message = str(e)
            methodology_note = ""
            chart_payload = None
    else:
        methodology_note = (
            "Set filters and click Run analysis to start scoring. "
            "This screen now opens quickly without auto-running heavy analysis."
        )

    category_records: list[dict] = []
    if category_table is not None and not category_table.empty:
        category_records = category_table.to_dict("records")

    feedback_by_question: dict[int, str] = {}
    analysis_session_ids_ordered: list[int] = []
    sessions_published_nominated_exam: set[int] = set()
    nominated_access_codes_by_session: dict[int, list[str]] = {}
    if analysis_rows:
        qids = [a.question_id for a in analysis_rows]
        fb_rows = (
            db.query(QuestionAnalysisFeedback)
            .filter(QuestionAnalysisFeedback.question_id.in_(qids))
            .all()
        )
        feedback_by_question = {r.question_id: (r.instructor_note or "") for r in fb_rows}
        seen_s: set[int] = set()
        for a in analysis_rows:
            if a.session_id not in seen_s:
                seen_s.add(a.session_id)
                analysis_session_ids_ordered.append(a.session_id)
        if seen_s:
            pub_rows = (
                db.query(NominatedExam.source_session_id)
                .filter(NominatedExam.source_session_id.in_(seen_s))
                .distinct()
                .all()
            )
            sessions_published_nominated_exam = {int(r[0]) for r in pub_rows if r[0] is not None}

            nom_rows = (
                db.query(NominatedExam.source_session_id, NominatedExam.access_code)
                .filter(NominatedExam.source_session_id.in_(seen_s))
                .order_by(NominatedExam.created_at.desc())
                .all()
            )
            for sid, code in nom_rows:
                if sid is None or not code:
                    continue
                k = int(sid)
                nominated_access_codes_by_session.setdefault(k, []).append(str(code).strip().upper())

    nomination_panel_sessions: list[ExamSession] = []
    if analysis_session_ids_ordered:
        order_map = {sid: i for i, sid in enumerate(analysis_session_ids_ordered)}
        sp = db.query(ExamSession).filter(ExamSession.id.in_(analysis_session_ids_ordered)).all()
        nomination_panel_sessions = sorted(sp, key=lambda s: order_map.get(s.id, 9999))

    fq = filter_query_string(state)
    fq_scored = filter_query_string(state, run="1")

    nominated_sessions_summary: str = ""
    if analysis_session_ids_ordered and analysis_rows:
        n_sessions = len(analysis_session_ids_ordered)
        n_pub = len(sessions_published_nominated_exam)
        nominated_sessions_summary = (
            f"In this sample, {n_pub} of {n_sessions} exam session(s) have a nominated exam "
            f"published for students; the rest do not yet. Open Nominated exams to publish or review."
        )

    return {
        "education_levels": EDUCATION_LEVELS,
        "sessions_picklist": recent_sessions,
        "session_id": state.session_id,
        "education_level": state.education_level,
        "llm_mode": state.llm_mode,
        "compare_by": state.compare_by,
        "compare_options": COMPARE_OPTIONS,
        "compare_by_help": ANALYSIS_COMPARE_BY_HELP,
        "llm_filter_help": ANALYSIS_LLM_FILTER_HELP,
        "sample_limit": state.sample_limit,
        "run_analysis": state.run_analysis,
        "analysis_rows": analysis_rows,
        "methodology_note": methodology_note,
        "chart_payload": chart_payload,
        "category_records": category_records,
        "compare_by_label": COMPARE_OPTIONS.get(state.compare_by, "Category"),
        "error_message": error_message,
        "feedback_by_question": feedback_by_question,
        "sessions_published_nominated_exam": sessions_published_nominated_exam,
        "nominated_access_codes_by_session": nominated_access_codes_by_session,
        "analysis_session_ids_ordered": analysis_session_ids_ordered,
        "uses_remote_agent": uses_remote_agent,
        "nomination_panel_sessions": nomination_panel_sessions,
        "filter_query": fq,
        "url_nomination": f"/professor/question-analysis/nomination?{fq_scored}",
        "url_manual_feedback": f"/professor/question-analysis/manual-feedback?{fq_scored}",
        "url_analysis_main": f"/professor/question-analysis?{fq}",
        "url_analysis_scored": f"/professor/question-analysis?{fq_scored}",
        "nominated_sessions_summary": nominated_sessions_summary,
    }
