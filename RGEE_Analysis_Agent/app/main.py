"""RGEE_Analysis_Agent — FastAPI service for semantic exam-question scoring."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.analysis_engine import DEFAULT_MODEL, analyze_questions_semantic
from app.config import get_settings
from app.db import get_db, init_db, persist_analysis_run


def _check_secret(request: Request) -> None:
    secret = get_settings().api_secret.strip()
    if not secret:
        return
    if request.headers.get("X-RGEE-Analysis-Secret", "") != secret:
        raise HTTPException(status_code=401, detail="Invalid or missing X-RGEE-Analysis-Secret header")


class AnalyzeQuestionIn(BaseModel):
    session_id: int
    exam_code: str | None = None
    question_id: int
    question_index: int
    education_level: str = ""
    use_mock_llm: bool = False
    essay_question: str = ""
    professor_domain: str = ""
    background_information: str = ""


class AnalyzeRequest(BaseModel):
    questions: list[AnalyzeQuestionIn]
    model_name: str | None = None
    sample_limit: int | None = Field(default=None, ge=1, le=5000)
    source: str = "rgee-main"
    persist: bool = True


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="RGEE_Analysis_Agent", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "RGEE_Analysis_Agent"}


@app.post("/internal/v1/analyze")
def run_analyze(
    request: Request,
    body: AnalyzeRequest,
    db: Session = Depends(get_db),
) -> dict:
    _check_secret(request)
    rows_in = [q.model_dump() for q in body.questions]
    model = (body.model_name or "").strip() or get_settings().question_analysis_st_model or DEFAULT_MODEL
    analysis_rows, note = analyze_questions_semantic(
        rows_in,
        model_name=model,
        sample_limit=body.sample_limit,
    )
    out_dicts = [asdict(a) for a in analysis_rows]
    if body.persist:
        persist_analysis_run(
            db,
            source=body.source[:128],
            methodology_note=note,
            rows=out_dicts,
        )
    return {"methodology_note": note, "rows": out_dicts}
