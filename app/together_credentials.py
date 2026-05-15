"""Together.ai Project API keys: OS keychain when available, Fernet-at-rest fallback.

Resolution order used for live Together calls:
1. OS credential store (keyring — Keychain Services on macOS, etc.)
2. Encrypted blob under the per-user credential directory (AES via Fernet)
3. Environment / .env (TOGETHER_API_KEY) — least preferred for workstations

Override credential directory with RGEE_CREDENTIAL_DATA_DIR for containers or tests.
"""

from __future__ import annotations

import logging
import os
import stat
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "com.rgee.RubricGuidedEssayExam"
KEYRING_USERNAME = "TOGETHER_API_KEY"
_TOGETHER_CIPHERTEXT = "together_api_key.enc"
_FERNET_KEY_FILE = ".rgee_machine_fernet"

_MAX_KEY_LEN = 4096


def _chmod_owner_rw(p: Path) -> None:
    try:
        if os.name == "posix" and p.exists():
            p.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def credential_data_directory() -> Path:
    raw = (os.environ.get("RGEE_CREDENTIAL_DATA_DIR") or "").strip()
    if raw:
        root = Path(raw).expanduser().resolve()
    elif os.name == "nt":
        home = Path.home()
        local = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
        root = (local / "RubricGuidedEssayExam" / "credentials").resolve()
    elif sys.platform == "darwin":
        root = (
            Path.home() / "Library" / "Application Support" / "RubricGuidedEssayExam" / "credentials"
        ).resolve()
    else:
        root = (
            Path.home() / ".local" / "share" / "rubric-guided-essay-exam" / "credentials"
        ).resolve()

    root.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            root.chmod(stat.S_IRWXU)
        except OSError:
            pass
    return root


_fernet: Fernet | None = None


def _machine_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    dirp = credential_data_directory()
    kpath = dirp / _FERNET_KEY_FILE
    if not kpath.exists():
        kpath.write_bytes(Fernet.generate_key())
        _chmod_owner_rw(kpath)
    key = kpath.read_bytes().strip()
    _fernet = Fernet(key)
    return _fernet


def reset_fernet_cache_for_tests() -> None:
    """Test helper: credential dir changed between tests."""
    global _fernet
    _fernet = None


def _read_encrypted_file() -> str | None:
    p = credential_data_directory() / _TOGETHER_CIPHERTEXT
    if not p.exists():
        return None
    try:
        plain = _machine_fernet().decrypt(p.read_bytes()).decode("utf-8").strip()
        return plain or None
    except InvalidToken:
        logger.warning(
            "Could not decrypt stored Together API key (%s); remove the file or clear credentials.", p
        )
        return None
    except OSError as e:
        logger.warning("Could not read encrypted Together credential file: %s", e)
        return None


def _write_encrypted_file(secret_plain: str) -> Path:
    token = _machine_fernet().encrypt(secret_plain.encode("utf-8"))
    p = credential_data_directory() / _TOGETHER_CIPHERTEXT
    p.write_bytes(token)
    _chmod_owner_rw(p)
    return p


def _delete_encrypted_file() -> None:
    p = credential_data_directory() / _TOGETHER_CIPHERTEXT
    try:
        p.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("Could not delete encrypted credential file %s: %s", p, e)


def _read_keyring() -> str | None:
    try:
        import keyring
    except ImportError:
        return None
    try:
        raw = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        v = (raw or "").strip()
        return v or None
    except Exception as e:
        logger.debug("Keyring read failed: %s", e)
        return None


def _write_keyring(secret_plain: str) -> bool:
    try:
        import keyring
    except ImportError:
        return False
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, secret_plain.strip())
        return True
    except Exception as e:
        logger.warning("Saving to OS keychain failed; using encrypted file fallback. Cause: %s", e)
        return False


def _delete_keyring() -> None:
    try:
        import keyring
    except ImportError:
        return
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:
        pass


def resolved_together_api_key() -> str:
    kr = (_read_keyring() or "").strip()
    if kr:
        return kr
    enc = (_read_encrypted_file() or "").strip()
    if enc:
        return enc
    return str(get_settings().together_api_key or "").strip()


def keychain_backend_hint() -> str:
    """Short label for the UI (diagnostics)."""
    try:
        import keyring

        kr = keyring.get_keyring()
        return f"{type(kr).__name__}"
    except Exception:
        return "keyring unavailable"


def together_credentials_snapshot() -> dict:
    """Instructor-facing status (never includes the raw key)."""
    keyring_val = (_read_keyring() or "").strip()
    encrypted_val = (_read_encrypted_file() or "").strip()
    env_val = str(get_settings().together_api_key or "").strip()

    active = resolved_together_api_key()
    mask = _masked_suffix(active)

    resolved_source = "none"
    if keyring_val:
        resolved_source = "keychain"
    elif encrypted_val:
        resolved_source = "encrypted_file"
    elif env_val:
        resolved_source = "env_file"

    return {
        "resolved_configured": bool(active),
        "resolved_source": resolved_source,
        "mask": mask,
        "vault_keychain": bool(keyring_val),
        "vault_encrypted_file": bool(encrypted_val),
        "env_fallback_set": bool(env_val),
        "encrypted_path_display": str(credential_data_directory() / _TOGETHER_CIPHERTEXT),
        "keyring_backend_hint": keychain_backend_hint(),
    }


def _masked_suffix(secret: str) -> str:
    s = (secret or "").strip()
    if not s:
        return "Not set"
    if len(s) <= 12:
        return "Saved (hidden)"
    return "••••" + s[-4:]


def normalize_new_key(raw: str) -> str:
    s = (raw or "").strip().strip('"').strip("'")
    if not s:
        raise ValueError("API key is empty.")
    if len(s) > _MAX_KEY_LEN:
        raise ValueError("API key looks too long to be valid.")
    return s


def store_together_api_key(secret_plain: str) -> tuple[str, str]:
    """Persist key securely. Returns (method, friendly detail for UI banners)."""
    s = normalize_new_key(secret_plain)
    if _write_keyring(s):
        _delete_encrypted_file()
        return ("keychain", "Saved to the OS secure keychain (recommended). Live calls will use this key.")
    enc_path = _write_encrypted_file(s)
    return (
        "encrypted_file",
        f"OS keychain was not available — saved AES-encrypted on disk only: {enc_path}. "
        "Restrict access to this user account.",
    )


def clear_vault_credentials() -> str:
    """Remove keychain and encrypted-file copies. Does not edit .env."""
    had_keychain = bool((_read_keyring() or "").strip())
    had_file = (credential_data_directory() / _TOGETHER_CIPHERTEXT).exists()

    _delete_keyring()
    _delete_encrypted_file()

    if not had_keychain and not had_file:
        return "No vault-stored Together key was found (nothing removed from secure storage)."

    parts = []
    if had_keychain:
        parts.append("OS keychain")
    if had_file:
        parts.append("encrypted disk file")
    env_set = bool(str(get_settings().together_api_key or "").strip())
    tail = ""
    if env_set:
        tail = " Together calls can still read TOGETHER_API_KEY from environment / .env until you unset it."
    else:
        tail = (
            " Production exams will fall back on Mock unless you paste a key again "
            "or configure TOGETHER_API_KEY."
        )
    return f"Removed secure storage ({', '.join(parts)}).{tail}"
