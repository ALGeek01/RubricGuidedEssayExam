"""HTTP client for the parallel RGEE_Analysis_Agent scoring service."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.question_analysis import QuestionAnalysisRow

logger = logging.getLogger(__name__)


def question_row_from_agent_dict(d: dict[str, Any]) -> QuestionAnalysisRow:
    return QuestionAnalysisRow(
        session_id=int(d["session_id"]),
        exam_code=d.get("exam_code"),
        question_id=int(d["question_id"]),
        question_index=int(d["question_index"]),
        education_level=str(d.get("education_level") or ""),
        use_mock_llm=bool(d.get("use_mock_llm")),
        essay_question=str(d.get("essay_question") or ""),
        professor_domain=str(d.get("professor_domain") or ""),
        background_information=str(d.get("background_information") or ""),
        relevance_score=float(d["relevance_score"]),
        quality_score=float(d["quality_score"]),
        humor_score=float(d["humor_score"]),
        quality_code=int(d["quality_code"]),
        quality_code_rationale=str(d.get("quality_code_rationale") or ""),
        grade_appropriateness_code=int(d["grade_appropriateness_code"]),
        grade_appropriateness_rationale=str(d.get("grade_appropriateness_rationale") or ""),
        relevance_notes=str(d.get("relevance_notes") or ""),
        quality_notes=str(d.get("quality_notes") or ""),
        humor_notes=str(d.get("humor_notes") or ""),
    )


async def analyze_questions_via_agent(
    rows: list[dict[str, Any]],
    *,
    sample_limit: int | None,
    model_name: str,
) -> tuple[list[QuestionAnalysisRow], str]:
    settings = get_settings()
    base = (settings.analysis_agent_base_url or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("RGEE_ANALYSIS_AGENT_URL is not set")

    timeout = httpx.Timeout(settings.analysis_agent_timeout_seconds)
    headers: dict[str, str] = {}
    secret = (settings.analysis_agent_api_secret or "").strip()
    if secret:
        headers["X-RGEE-Analysis-Secret"] = secret

    payload: dict[str, Any] = {
        "questions": rows,
        "model_name": model_name,
        "source": "rgee-main",
        "persist": True,
    }
    if sample_limit is not None and sample_limit > 0:
        payload["sample_limit"] = sample_limit

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{base}/internal/v1/analyze", json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = (e.response.text or "")[:500]
        except Exception:
            pass
        logger.warning("Analysis agent HTTP %s: %s", e.response.status_code, body)
        raise RuntimeError(
            f"RGEE_Analysis_Agent returned HTTP {e.response.status_code}. "
            "Check agent logs and shared secret configuration."
        ) from e
    except httpx.RequestError as e:
        logger.warning("Analysis agent unreachable: %s", e)
        raise RuntimeError(
            "Could not reach RGEE_Analysis_Agent. Start ./scripts/launch_analysis_agent.sh and set "
            f"RGEE_ANALYSIS_AGENT_URL (this app is configured for {base!r})."
        ) from e

    note = str(data.get("methodology_note") or "")
    raw_rows = data.get("rows") or []
    parsed = [question_row_from_agent_dict(x) for x in raw_rows]
    return parsed, note + " · Scoring ran in RGEE_Analysis_Agent (separate process)."
