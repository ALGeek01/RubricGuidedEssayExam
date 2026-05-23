"""Instructor area auth using one-way derived secrets (SHA-256 username, PBKDF2-HMAC-SHA256 password)."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from pathlib import Path

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# PBKDF2 parameters for instructor password verification.
PBKDF2_SALT = b"rgee-instructor-v1"
PBKDF2_ITERATIONS = 210_000

# Test / local-dev defaults (username "elliott", password "12345"). Not written when RGEE_PRODUCTION=1.
DEFAULT_USERNAME_SHA256 = "0f9c00b3f38f964ee172095f50e53fe9b9e01bd0e1a9f750d877bd26a84ffe18"
DEFAULT_PASSWORD_PBKDF2_HEX = (
    "b9ccfa56ff91bb8e916a6c836ec754ba32b5b01e17d85eaa731bb1b8cf66a4ee"
)

SESSION_KEY = "instructor_ok"


def credentials_path(base_dir: Path, settings: Settings) -> Path:
    raw = (settings.instructor_credentials_path or "").strip()
    return Path(raw) if raw else (base_dir / "instructor_credentials.json")


def ensure_instructor_credentials_file(path: Path) -> None:
    """Create JSON with derived values only (no plaintext) when missing."""
    if path.exists():
        return
    settings = get_settings()
    path.parent.mkdir(parents=True, exist_ok=True)
    if settings.rgee_production:
        raise RuntimeError(
            f"Instructor credentials file missing at {path}. "
            "Create it with username_sha256 and password_pbkdf2_hex before running in production."
        )
    payload = {
        "version": 1,
        "username_sha256": DEFAULT_USERNAME_SHA256,
        "password_pbkdf2_hex": DEFAULT_PASSWORD_PBKDF2_HEX,
        "pbkdf2_iterations": PBKDF2_ITERATIONS,
        "_note": "Development defaults (elliott / 12345). Change before any public deployment.",
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    logger.warning(
        "Created development instructor credentials at %s (default username/password). "
        "Replace before production.",
        path,
    )


def _pbkdf2_hex(password: str, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        PBKDF2_SALT,
        iterations,
    ).hex()


def _load_expected_from_file(path: Path) -> tuple[str, str, int] | None:
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        u = data.get("username_sha256")
        p = data.get("password_pbkdf2_hex")
        if u is None or p is None:
            return None
        it_raw = data.get("pbkdf2_iterations", PBKDF2_ITERATIONS)
        iterations = int(it_raw)
        if iterations < 1 or iterations > 2_000_000:
            iterations = PBKDF2_ITERATIONS
        return (str(u).strip(), str(p).strip(), iterations)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as e:
        logger.warning("Ignoring invalid instructor credentials file %s: %s", path, e)
        return None


def expected_instructor_derivatives(
    base_dir: Path, settings: Settings
) -> tuple[str, str, int]:
    path = credentials_path(base_dir, settings)
    from_file = _load_expected_from_file(path)
    if from_file is not None:
        return from_file
    u = (settings.instructor_username_sha256 or "").strip() or DEFAULT_USERNAME_SHA256
    p = (settings.instructor_password_pbkdf2_hex or "").strip() or DEFAULT_PASSWORD_PBKDF2_HEX
    return (u, p, PBKDF2_ITERATIONS)


def verify_instructor_login(
    username: str, password: str, base_dir: Path, settings: Settings
) -> bool:
    try:
        exp_user, exp_pw_hex, iterations = expected_instructor_derivatives(base_dir, settings)
        if iterations < 1 or iterations > 2_000_000:
            iterations = PBKDF2_ITERATIONS
        user_digest = hashlib.sha256(username.encode("utf-8")).hexdigest()
        try:
            if not secrets.compare_digest(user_digest, exp_user):
                return False
        except (TypeError, ValueError):
            return False
        try:
            derived = bytes.fromhex(_pbkdf2_hex(password, iterations))
            expected = bytes.fromhex(exp_pw_hex)
        except ValueError:
            return False
        try:
            return secrets.compare_digest(derived, expected)
        except (TypeError, ValueError):
            return False
    except Exception as e:
        logger.warning("Instructor login verification error (%s): %s", type(e).__name__, e)
        return False


def instructor_session_ok(request) -> bool:
    return bool(request.session.get(SESSION_KEY))
