"""Security helpers: headers, CSRF, exam access tokens, input limits, production checks."""

from __future__ import annotations

import logging
import secrets
from html import escape

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

CSRF_SESSION_KEY = "csrf_token"
EXAM_ACCESS_SESSION_KEY = "exam_access_tokens"

MAX_STUDENT_ID_LEN = 256
MAX_PROFESSOR_DOMAIN_LEN = 8_000
MAX_ANSWER_LEN = 50_000
MAX_HINT_QUERY_WORDS = 100

DEFAULT_DEV_SESSION_SECRET = "rgee-instructor-session-dev-key-min-32-chars!!"


def csrf_enabled() -> bool:
    return get_settings().csrf_enabled


def get_csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


def validate_csrf(request: Request, form_token: str | None) -> bool:
    if not csrf_enabled():
        return True
    expected = request.session.get(CSRF_SESSION_KEY)
    if not isinstance(expected, str) or not expected:
        return False
    submitted = (form_token or "").strip()
    if not submitted:
        return False
    try:
        return secrets.compare_digest(submitted, expected)
    except (TypeError, ValueError):
        return False


def require_csrf(request: Request, form_token: str | None) -> None:
    if not validate_csrf(request, form_token):
        raise HTTPException(
            status_code=403,
            detail="Invalid or missing CSRF token. Refresh the page and try again.",
        )


def grant_exam_access(request: Request, session_id: int) -> None:
    token = secrets.token_urlsafe(32)
    raw = request.session.get(EXAM_ACCESS_SESSION_KEY)
    tokens: dict[str, str] = dict(raw) if isinstance(raw, dict) else {}
    tokens[str(session_id)] = token
    request.session[EXAM_ACCESS_SESSION_KEY] = tokens


def require_exam_access(request: Request, session_id: int) -> None:
    raw = request.session.get(EXAM_ACCESS_SESSION_KEY)
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=403,
            detail="Exam access denied. Start or resume your exam with your student ID and exam ID.",
        )
    expected = raw.get(str(session_id))
    if not expected:
        raise HTTPException(
            status_code=403,
            detail="Exam access denied. Start or resume your exam with your student ID and exam ID.",
        )


def truncate_field(value: str, max_len: int) -> str:
    return (value or "").strip()[:max_len]


def validate_production_security(settings: Settings) -> None:
    if not settings.rgee_production:
        logger.info("RGEE_PRODUCTION is off; using development security defaults.")
        return
    if settings.instructor_session_secret == DEFAULT_DEV_SESSION_SECRET:
        raise RuntimeError(
            "INSTRUCTOR_SESSION_SECRET must be set to a unique random value when RGEE_PRODUCTION=1."
        )
    if settings.csrf_enabled is False:
        raise RuntimeError("CSRF protection cannot be disabled when RGEE_PRODUCTION=1.")
    if settings.analysis_agent_base_url.strip() and not settings.analysis_agent_api_secret.strip():
        raise RuntimeError(
            "RGEE_ANALYSIS_AGENT_SECRET must be set when RGEE_ANALYSIS_AGENT_URL is configured in production."
        )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/") or path.startswith("/assets/"):
            return response
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net data:; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )
        settings = get_settings()
        if settings.rgee_production or settings.session_https_only:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


def csrf_token_for_template(request: Request) -> str:
    return escape(get_csrf_token(request))
