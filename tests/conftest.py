"""Configure test env before any app modules load (engine binds at import time)."""
import os
import tempfile

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
_db_path = _tmp.name.replace("\\", "/")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
os.environ["MOCK_LLM"] = "1"

_cred_dir = tempfile.mkdtemp()
os.environ["INSTRUCTOR_CREDENTIALS_PATH"] = os.path.join(_cred_dir, "instructor_credentials.json")
os.environ["INSTRUCTOR_SESSION_SECRET"] = "test-instructor-session-secret-32chars!!"
os.environ["RGEE_MOCK_QUESTION_ANALYSIS"] = "1"
os.environ["RGEE_CSRF_ENABLED"] = "0"

import json

from app.instructor_auth import (
    DEFAULT_PASSWORD_PBKDF2_HEX,
    DEFAULT_USERNAME_SHA256,
    PBKDF2_ITERATIONS,
)

with open(os.environ["INSTRUCTOR_CREDENTIALS_PATH"], "w", encoding="utf-8") as _cred_f:
    json.dump(
        {
            "version": 1,
            "username_sha256": DEFAULT_USERNAME_SHA256,
            "password_pbkdf2_hex": DEFAULT_PASSWORD_PBKDF2_HEX,
            "pbkdf2_iterations": PBKDF2_ITERATIONS,
        },
        _cred_f,
    )

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def logged_in_instructor(client: TestClient):
    r = client.post(
        "/professor/login",
        data={"username": "elliott", "password": "12345", "next": "/professor"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    return client


@pytest.fixture(autouse=True)
def reset_db():
    from app.database import Base, engine

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
