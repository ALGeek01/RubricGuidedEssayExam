"""Security control tests (access tokens, CSRF, headers)."""

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.security


def _start_exam(client: TestClient) -> int:
    r = client.post(
        "/exam/start",
        data={
            "student_id": "sec-student",
            "professor_domain": "Security test topic.",
            "num_questions": "1",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    return int(r.headers["location"].split("/exam/")[1].split("/")[0])


def test_exam_routes_require_session_access_token(client: TestClient):
    """Without start/resume in this browser session, exam pages are forbidden."""
    session_id = _start_exam(client)
    outsider = TestClient(client.app)
    assert outsider.get(f"/exam/{session_id}/question").status_code == 403
    assert outsider.get(f"/exam/{session_id}/results").status_code == 403


def test_security_headers_present(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert "content-security-policy" in r.headers


def test_csrf_blocks_instructor_login_without_token(monkeypatch):
    monkeypatch.setenv("RGEE_CSRF_ENABLED", "1")
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        page = c.get("/professor/login")
        assert page.status_code == 200
        r = c.post(
            "/professor/login",
            data={"username": "elliott", "password": "12345", "next": "/professor"},
            follow_redirects=False,
        )
        assert r.status_code == 403
    get_settings.cache_clear()
