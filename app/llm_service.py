import json
import re
import time
from typing import Any

import httpx

from app.config import get_settings
from app.together_credentials import resolved_together_api_key
from app.perf_logging import log_performance_event
from app.errors import TogetherApiError
from app.education_levels import guidance_for_level, label_for_level
from app.grading_strictness import (
    DEFAULT_GRADING_STRICTNESS,
    guidance_for_strictness,
    label_for_strictness,
    mock_percent_for_strictness,
    normalize_strictness,
)
from app.prompts import (
    AI_HELPER_TEMPLATE,
    COMBINED_GRADE_AND_FINAL_TEMPLATE,
    COMBINED_GRADE_AND_NEXT_QUESTION_TEMPLATE,
    FINAL_GRADE_TEMPLATE,
    GRADE_RESPONSE_TEMPLATE,
    QUESTION_GENERATION_TEMPLATE,
    SAFE_HINT_TEMPLATE,
)


def _strip_json_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = _strip_json_fence(text)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            return json.loads(m.group())
        raise


def _parse_or_repair_json_object(
    text: str,
    *,
    expected_top_level_keys: list[str] | None = None,
    exam_session_id: int | None = None,
    llm_call_name: str = "json_repair",
) -> dict[str, Any]:
    """Parse model output as JSON; on failure, ask the model once to repair to valid JSON."""
    try:
        return _parse_json_object(text)
    except json.JSONDecodeError:
        keys_hint = ", ".join(expected_top_level_keys or [])
        repair_prompt = (
            "Rewrite the following content as ONE valid JSON object only. "
            "Do not wrap in markdown or explanations."
        )
        if keys_hint:
            repair_prompt += f" Preserve these top-level keys: {keys_hint}."
        repair_prompt += "\n\nContent to repair:\n" + text
        repaired = _chat_completion(
            [
                {
                    "role": "system",
                    "content": "You are a JSON repair tool. Output only strict valid JSON.",
                },
                {"role": "user", "content": repair_prompt},
            ],
            max_tokens=8192,
            exam_session_id=exam_session_id,
            llm_call_name=llm_call_name,
        )
        try:
            return _parse_json_object(repaired)
        except json.JSONDecodeError as e:
            raise TogetherApiError(
                "Together.ai returned malformed JSON and repair failed. Please try again.",
                http_status=503,
            ) from e


def _mock_question_payload(professor_domain: str, q_index: int, education_level: str) -> dict[str, Any]:
    return {
        "background_information": (
            f"[MOCK] Brief context for domain snippet: {professor_domain[:120]}..."
            if len(professor_domain) > 120
            else f"[MOCK] Brief context for: {professor_domain}"
        ),
        "essay_question": (
            f"[MOCK Question {q_index + 1}] Explain two main ideas from the domain guidance above "
            "and how they connect to fair assessment in asynchronous courses."
        ),
        "grading_rubric": [
            "Names at least two distinct ideas from the domain",
            "Explains the connection between those ideas clearly",
            "Discusses assessment or async context in a substantive way",
        ],
        "domain_notes": f"Mock mode: no live LLM. Education level: {label_for_level(education_level)}.",
    }


def _mock_grade_payload(grading_strictness: str = DEFAULT_GRADING_STRICTNESS) -> dict[str, Any]:
    m = normalize_strictness(grading_strictness)
    pct = mock_percent_for_strictness(m)
    label = label_for_strictness(m)
    return {
        "highly_satisfactory": pct >= 80,
        "dimension_scores": {
            "rubric_alignment": round(max(0, min(100, pct - 2))),
            "completeness": round(max(0, min(100, pct - 4))),
            "clarity": round(max(0, min(100, pct + 1))),
        },
        "overall_percent": pct,
        "explanation": (
            f"[MOCK] Demo score for grading mode “{label}”. "
            "In Production, the model applies this strictness to rubric-based scoring."
        ),
    }


def _mock_final_payload(grading_strictness: str = DEFAULT_GRADING_STRICTNESS) -> dict[str, Any]:
    m = normalize_strictness(grading_strictness)
    pct = mock_percent_for_strictness(m)
    label = label_for_strictness(m)
    return {
        "total_grade_percent": pct,
        "explanation": f"[MOCK] Demo overall grade for “{label}” strictness (equal weight per question in mock).",
        "weighting_notes": "Equal weight per question in mock.",
    }


def _mock_hint_payload() -> dict[str, Any]:
    return {
        "status": "ok",
        "hint": "[MOCK Hint] Start by defining the core concept in one sentence, then connect it to one concrete example from the prompt.",
    }


def _mock_ai_helper_payload(student_question: str, selected_hint: str) -> dict[str, Any]:
    q = (student_question or "").strip()
    h = (selected_hint or "").strip()
    if not q:
        return {
            "status": "ok",
            "reply": "[MOCK AI Helper] Ask a specific follow-up and I will guide your next step without giving the final answer.",
        }
    q_preview = q[:220]
    if h:
        h_preview = h[:220]
        return {
            "status": "ok",
            "reply": (
                "[MOCK AI Helper] Based on your question: "
                f"\"{q_preview}\", start from this hint context: \"{h_preview}\". "
                "Explain one intermediate step in your own words, then check if it still aligns with the prompt."
            ),
        }
    return {
        "status": "ok",
        "reply": (
            "[MOCK AI Helper] You asked: "
            f"\"{q_preview}\". "
            "Focus on one concrete intermediate step and justify why that step is valid before continuing."
        ),
    }


def _together_error_json_message(e: httpx.HTTPStatusError) -> str:
    """Short user-facing detail from Together JSON error body."""
    try:
        body = e.response.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict) and err.get("message"):
                return str(err["message"]).strip()
    except Exception:
        pass
    return (e.response.text or "")[:300]


def _chat_completion(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 4096,
    exam_session_id: int | None = None,
    llm_call_name: str = "together_chat",
) -> str:
    t0 = time.perf_counter()
    s = get_settings()
    api_key = resolved_together_api_key()
    if not api_key:
        raise TogetherApiError(
            "Together.ai API key is missing. Signed-in instructors can save it securely under "
            "/professor/together-credentials, or set TOGETHER_API_KEY in .env. Otherwise use Mock mode.",
            http_status=503,
        )
    url = f"{s.together_base_url.rstrip('/')}/chat/completions"
    body = {
        "model": s.together_model_for_requests(),
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": max_tokens,
    }
    try:
        with httpx.Client(timeout=120.0) as client:
            r = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        snippet = ""
        try:
            snippet = (e.response.text or "")[:600]
        except Exception:
            pass
        code = e.response.status_code
        if code in (401, 403):
            raise TogetherApiError(
                "Together.ai rejected your API key (401/403). "
                "Create a new Project API key at "
                "https://api.together.ai/settings/api-keys "
                "(sign in → your project → API Keys), copy the full key, "
                "paste the full key again under Instructor → Together.ai API key "
                "(or set TOGETHER_API_KEY in .env) with no extra spaces or quotes. "
                "Keys are only shown once when created. "
                "Until this is fixed, use Mock mode on the home page.",
                http_status=503,
            ) from e
        if code == 402:
            # Valid key; billing / credits — common on 2nd+ API call when quota is tight
            detail = _together_error_json_message(e)
            raise TogetherApiError(
                "Together.ai: credit limit or billing issue (HTTP 402).\n\n"
                "Your API key is accepted; this is not a wrong token. "
                "Add credits or a payment method at:\n"
                "https://api.together.ai/settings/billing\n\n"
                f"Details from Together: {detail}\n\n"
                "Or choose Mock (testing) on the home page to use the app without live API calls.",
                http_status=503,
            ) from e
        raise TogetherApiError(
            f"Together.ai request failed (HTTP {code}). {snippet}",
            http_status=503,
        ) from e
    except httpx.RequestError as e:
        raise TogetherApiError(
            f"Could not reach Together.ai: {e!s}",
            http_status=503,
        ) from e
    finally:
        log_performance_event(
            "llm",
            llm_call_name,
            (time.perf_counter() - t0) * 1000,
            exam_session_id=exam_session_id,
            meta={"model": s.together_model_for_requests(), "endpoint": "chat/completions"},
        )

    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise TogetherApiError(
            f"Unexpected response from Together.ai: {data!r}"[:800],
            http_status=503,
        ) from e


def generate_question(
    professor_domain: str,
    prior_questions_summary: str,
    question_index: int = 0,
    education_level: str = "college",
    *,
    use_mock: bool = True,
    exam_session_id: int | None = None,
) -> dict[str, Any]:
    if use_mock:
        return _mock_question_payload(professor_domain, question_index, education_level)

    prompt = QUESTION_GENERATION_TEMPLATE.format(
        education_level_label=label_for_level(education_level),
        education_level_guidance=guidance_for_level(education_level),
        professor_domain=professor_domain,
        prior_questions_summary=prior_questions_summary or "(none yet)",
    )
    content = _chat_completion(
        [
            {"role": "system", "content": "You output only valid JSON objects for exam software."},
            {"role": "user", "content": prompt},
        ],
        exam_session_id=exam_session_id,
        llm_call_name="generate_question",
    )
    return _parse_json_object(content)


def grade_and_next_question_combined(
    professor_domain: str,
    prior_questions_summary: str,
    next_question_index: int,
    background_information: str,
    essay_question: str,
    grading_rubric: str,
    student_response: str,
    seconds_on_question: int | None,
    education_level: str = "college",
    *,
    grading_strictness: str = DEFAULT_GRADING_STRICTNESS,
    use_mock: bool = True,
    exam_session_id: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Single API call: grade current answer + generate next question (saves one round trip)."""
    if use_mock:
        return (
            _mock_grade_payload(grading_strictness),
            _mock_question_payload(professor_domain, next_question_index, education_level),
        )

    rubric_display = grading_rubric
    try:
        rubric_list = json.loads(grading_rubric)
        if isinstance(rubric_list, list):
            rubric_display = "\n".join(f"- {x}" for x in rubric_list)
    except json.JSONDecodeError:
        pass

    prompt = COMBINED_GRADE_AND_NEXT_QUESTION_TEMPLATE.format(
        education_level_label=label_for_level(education_level),
        education_level_guidance=guidance_for_level(education_level),
        grading_strictness_label=label_for_strictness(grading_strictness),
        grading_strictness_guidance=guidance_for_strictness(grading_strictness),
        professor_domain=professor_domain,
        prior_questions_summary=prior_questions_summary or "(none yet)",
        background_information=background_information,
        essay_question=essay_question,
        grading_rubric=rubric_display,
        student_response=student_response,
        seconds_on_question=seconds_on_question if seconds_on_question is not None else "not recorded",
        next_question_index=next_question_index,
    )
    content = _chat_completion(
        [
            {
                "role": "system",
                "content": "You grade one answer and author the next exam question. Output only valid JSON.",
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=8192,
        exam_session_id=exam_session_id,
        llm_call_name="grade_and_next_combined",
    )
    parsed = _parse_or_repair_json_object(
        content,
        expected_top_level_keys=["grading", "next_question"],
        exam_session_id=exam_session_id,
        llm_call_name="grade_and_next_combined_json_repair",
    )
    g = parsed.get("grading")
    nq = parsed.get("next_question")
    if not isinstance(g, dict) or not isinstance(nq, dict):
        raise TogetherApiError(
            "Together.ai returned invalid combined JSON (expected keys grading, next_question).",
            http_status=503,
        )
    return g, nq


def grade_and_final_combined(
    earlier_questions_graded_blob: str,
    background_information: str,
    essay_question: str,
    grading_rubric: str,
    student_response: str,
    seconds_on_question: int | None,
    education_level: str = "college",
    *,
    grading_strictness: str = DEFAULT_GRADING_STRICTNESS,
    use_mock: bool = True,
    exam_session_id: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Single API call: grade last answer + overall final grade (saves one round trip)."""
    if use_mock:
        return _mock_grade_payload(grading_strictness), _mock_final_payload(grading_strictness)

    rubric_display = grading_rubric
    try:
        rubric_list = json.loads(grading_rubric)
        if isinstance(rubric_list, list):
            rubric_display = "\n".join(f"- {x}" for x in rubric_list)
    except json.JSONDecodeError:
        pass

    prompt = COMBINED_GRADE_AND_FINAL_TEMPLATE.format(
        education_level_label=label_for_level(education_level),
        education_level_guidance=guidance_for_level(education_level),
        grading_strictness_label=label_for_strictness(grading_strictness),
        grading_strictness_guidance=guidance_for_strictness(grading_strictness),
        earlier_questions_graded_blob=earlier_questions_graded_blob or "(no prior questions — single-question exam)",
        background_information=background_information,
        essay_question=essay_question,
        grading_rubric=rubric_display,
        student_response=student_response,
        seconds_on_question=seconds_on_question if seconds_on_question is not None else "not recorded",
    )
    content = _chat_completion(
        [
            {
                "role": "system",
                "content": "You grade the last answer and synthesize an overall exam grade. Output only valid JSON.",
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=8192,
        exam_session_id=exam_session_id,
        llm_call_name="grade_and_final_combined",
    )
    parsed = _parse_or_repair_json_object(
        content,
        expected_top_level_keys=["grading", "final_grade"],
        exam_session_id=exam_session_id,
        llm_call_name="grade_and_final_combined_json_repair",
    )
    g = parsed.get("grading")
    fg = parsed.get("final_grade")
    if not isinstance(g, dict) or not isinstance(fg, dict):
        raise TogetherApiError(
            "Together.ai returned invalid combined JSON (expected keys grading, final_grade).",
            http_status=503,
        )
    return g, fg


def grade_answer(
    background_information: str,
    essay_question: str,
    grading_rubric: str,
    student_response: str,
    seconds_on_question: int | None,
    education_level: str = "college",
    *,
    grading_strictness: str = DEFAULT_GRADING_STRICTNESS,
    use_mock: bool = True,
    exam_session_id: int | None = None,
) -> dict[str, Any]:
    if use_mock:
        return _mock_grade_payload(grading_strictness)

    rubric_display = grading_rubric
    try:
        rubric_list = json.loads(grading_rubric)
        if isinstance(rubric_list, list):
            rubric_display = "\n".join(f"- {x}" for x in rubric_list)
    except json.JSONDecodeError:
        pass

    prompt = GRADE_RESPONSE_TEMPLATE.format(
        education_level_label=label_for_level(education_level),
        education_level_guidance=guidance_for_level(education_level),
        grading_strictness_label=label_for_strictness(grading_strictness),
        grading_strictness_guidance=guidance_for_strictness(grading_strictness),
        background_information=background_information,
        essay_question=essay_question,
        grading_rubric=rubric_display,
        student_response=student_response,
        seconds_on_question=seconds_on_question if seconds_on_question is not None else "not recorded",
    )
    content = _chat_completion(
        [
            {"role": "system", "content": "You are a fair, consistent exam grader. Output only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        exam_session_id=exam_session_id,
        llm_call_name="grade_answer",
    )
    return _parse_json_object(content)


def final_grade(
    per_question_summaries: list[dict[str, Any]],
    education_level: str = "college",
    *,
    grading_strictness: str = DEFAULT_GRADING_STRICTNESS,
    use_mock: bool = True,
    exam_session_id: int | None = None,
) -> dict[str, Any]:
    if use_mock:
        return _mock_final_payload(grading_strictness)

    blob = json.dumps(per_question_summaries, ensure_ascii=False, indent=2)
    prompt = FINAL_GRADE_TEMPLATE.format(
        education_level_label=label_for_level(education_level),
        education_level_guidance=guidance_for_level(education_level),
        grading_strictness_label=label_for_strictness(grading_strictness),
        grading_strictness_guidance=guidance_for_strictness(grading_strictness),
        per_question_summaries=blob,
    )
    content = _chat_completion(
        [
            {
                "role": "system",
                "content": "You synthesize exam results into one overall grade. Output only valid JSON.",
            },
            {"role": "user", "content": prompt},
        ],
        exam_session_id=exam_session_id,
        llm_call_name="final_grade",
    )
    return _parse_json_object(content)


def generate_safe_hint(
    *,
    essay_question: str,
    background_information: str,
    grading_rubric: str,
    student_text: str,
    education_level: str = "college",
    use_mock: bool = True,
    exam_session_id: int | None = None,
) -> dict[str, Any]:
    if use_mock:
        return _mock_hint_payload()

    rubric_display = grading_rubric
    try:
        rubric_list = json.loads(grading_rubric)
        if isinstance(rubric_list, list):
            rubric_display = "\n".join(f"- {x}" for x in rubric_list)
    except json.JSONDecodeError:
        pass

    prompt = SAFE_HINT_TEMPLATE.format(
        education_level_label=label_for_level(education_level),
        education_level_guidance=guidance_for_level(education_level),
        essay_question=essay_question,
        background_information=background_information,
        grading_rubric=rubric_display,
        student_text=student_text or "(empty)",
    )
    content = _chat_completion(
        [
            {"role": "system", "content": "You are a secure hint generator. Output only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=500,
        exam_session_id=exam_session_id,
        llm_call_name="generate_safe_hint",
    )
    return _parse_json_object(content)


def generate_ai_helper_reply(
    *,
    essay_question: str,
    background_information: str,
    selected_hint: str,
    student_question: str,
    education_level: str = "college",
    use_mock: bool = True,
    exam_session_id: int | None = None,
) -> dict[str, Any]:
    if use_mock:
        return _mock_ai_helper_payload(student_question, selected_hint)

    prompt = AI_HELPER_TEMPLATE.format(
        education_level_label=label_for_level(education_level),
        education_level_guidance=guidance_for_level(education_level),
        essay_question=essay_question,
        background_information=background_information,
        selected_hint=selected_hint or "(none selected)",
        student_question=student_question or "(empty)",
    )
    content = _chat_completion(
        [
            {"role": "system", "content": "You are a secure exam AI helper. Output only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=600,
        exam_session_id=exam_session_id,
        llm_call_name="generate_ai_helper_reply",
    )
    return _parse_json_object(content)
