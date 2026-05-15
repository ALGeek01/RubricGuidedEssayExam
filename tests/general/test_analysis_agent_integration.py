"""Integration: question analysis delegates to RGEE_Analysis_Agent over HTTP (httpx mocked)."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings


def _agent_row_dict(**overrides):
    base = {
        "session_id": 1,
        "exam_code": "ZZZZZ",
        "question_id": 999001,
        "question_index": 0,
        "education_level": "college",
        "use_mock_llm": True,
        "essay_question": "Agent-mock HTTP question text.",
        "professor_domain": "Mock domain via HTTP stub.",
        "background_information": "",
        "relevance_score": 6.1,
        "quality_score": 6.2,
        "humor_score": 4.3,
        "quality_code": 3,
        "quality_code_rationale": "stub quality",
        "grade_appropriateness_code": 3,
        "grade_appropriateness_rationale": "stub grade",
        "relevance_notes": "stub rel",
        "quality_notes": "stub qual",
        "humor_notes": "stub humor",
    }
    base.update(overrides)
    return base


@pytest.fixture
def mock_analysis_agent_http(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RGEE_ANALYSIS_AGENT_URL", "http://agent.test:8010")
    get_settings.cache_clear()

    class FakeResp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "methodology_note": "Mock agent HTTP integration note.",
                "rows": [_agent_row_dict()],
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url: str, json=None, headers=None):
            assert url.startswith("http://agent.test:8010/internal/v1/analyze")
            assert json is not None
            assert isinstance(json.get("questions"), list)
            assert len(json["questions"]) >= 1
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    yield
    get_settings.cache_clear()


def test_question_analysis_delegates_to_agent_when_url_set(
    mock_analysis_agent_http: None,
    logged_in_instructor: TestClient,
):
    logged_in_instructor.post(
        "/exam/start",
        data={
            "student_id": "agent-http-delegate",
            "professor_domain": "Domain for HTTP delegate integration test.",
            "num_questions": "1",
        },
        follow_redirects=False,
    )
    dash = logged_in_instructor.get("/professor/question-analysis?run=1")
    assert dash.status_code == 200
    assert "Exam question analysis" in dash.text
    assert "Mock agent HTTP integration note" in dash.text
    assert "RGEE_Analysis_Agent (separate process)" in dash.text
    assert "Agent-mock HTTP question text." in dash.text
    assert "Question-level detail" in dash.text


def test_question_analysis_agent_payload_matches_session_question(
    logged_in_instructor: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """POSTed question payload to the agent matches the exam row loaded from the DB."""
    monkeypatch.setenv("RGEE_ANALYSIS_AGENT_URL", "http://agent.test:8010")
    get_settings.cache_clear()

    captured: dict = {}

    class FakeResp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            q = captured.get("questions", [{}])[0]
            return {
                "methodology_note": "Echo mock.",
                "rows": [_agent_row_dict(**q)],
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url: str, json=None, headers=None):
            captured["questions"] = (json or {}).get("questions") or []
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    try:
        r0 = logged_in_instructor.post(
            "/exam/start",
            data={
                "student_id": "http-agent-payload-student",
                "professor_domain": "Payload verification domain for agent HTTP.",
                "num_questions": "1",
            },
            follow_redirects=False,
        )
        assert r0.status_code == 303

        dash = logged_in_instructor.get("/professor/question-analysis?run=1")
        assert dash.status_code == 200
        qs = captured.get("questions") or []
        assert len(qs) == 1
        assert qs[0]["essay_question"]
        assert "Payload verification domain for agent HTTP." in (
            qs[0].get("professor_domain") or ""
        )
        assert "http-agent-payload-student" in dash.text or qs[0].get("session_id")
    finally:
        get_settings.cache_clear()
        monkeypatch.delenv("RGEE_ANALYSIS_AGENT_URL", raising=False)
