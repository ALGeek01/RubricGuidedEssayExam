"""Unit tests for secure Together.ai credential helpers."""

from __future__ import annotations

import pytest

import app.config as app_config


@pytest.fixture
def credential_dir(monkeypatch, tmp_path):
    d = tmp_path / "cred-data"
    monkeypatch.setenv("RGEE_CREDENTIAL_DATA_DIR", str(d))
    app_config.get_settings.cache_clear()
    yield d
    app_config.get_settings.cache_clear()


def test_resolver_env_only(monkeypatch, credential_dir: object):
    import app.together_credentials as tc

    monkeypatch.setenv("TOGETHER_API_KEY", "from-env-plain")
    app_config.get_settings.cache_clear()
    monkeypatch.setattr(tc, "_read_keyring", lambda: None)
    monkeypatch.setattr(tc, "_read_encrypted_file", lambda: None)
    tc.reset_fernet_cache_for_tests()
    assert tc.resolved_together_api_key() == "from-env-plain"


def test_resolver_prefers_keyring(monkeypatch, credential_dir: object):
    import app.together_credentials as tc

    monkeypatch.setenv("TOGETHER_API_KEY", "from-env")
    app_config.get_settings.cache_clear()
    monkeypatch.setattr(tc, "_read_keyring", lambda: "from-keychain")
    monkeypatch.setattr(tc, "_read_encrypted_file", lambda: "from-disk")
    tc.reset_fernet_cache_for_tests()
    assert tc.resolved_together_api_key() == "from-keychain"


def test_encrypted_fallback_roundtrip(monkeypatch, credential_dir: object):
    import app.together_credentials as tc

    monkeypatch.setattr(tc, "_write_keyring", lambda _secret: False)
    monkeypatch.setenv("TOGETHER_API_KEY", "should-ignore")
    app_config.get_settings.cache_clear()

    monkeypatch.setattr(tc, "_read_keyring", lambda: None)

    tc.reset_fernet_cache_for_tests()

    tc.store_together_api_key("alice-secret-token")
    assert tc.resolved_together_api_key() == "alice-secret-token"


def test_credentials_requires_instructor_login(client):
    r = client.get("/professor/together-credentials", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location", "").startswith("/professor/login")


def test_strip_dotenv_exports_and_assignments(tmp_path):
    import app.together_credentials as tc

    d = tmp_path / ".env"
    d.write_text("# c\n export TOGETHER_API_KEY = abc \nFOO=keep\n")

    assert tc._strip_together_api_key_from_dotenv_path(d)
    body = d.read_text()
    assert "TOGETHER_API_KEY" not in body
    assert "FOO=keep" in body


def test_clear_strip_dotenv_candidates(monkeypatch, credential_dir: object):
    import app.together_credentials as tc

    wrk = credential_dir.parent
    monkeypatch.chdir(wrk)

    monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
    app_config.get_settings.cache_clear()

    dummy = wrk / ".env"
    dummy.write_text("OTHER=x\nTOGETHER_API_KEY=should-go\n")

    monkeypatch.setattr(tc, "_dotenv_candidate_paths", lambda: [dummy])

    tc.reset_fernet_cache_for_tests()
    monkeypatch.setattr(tc, "_read_keyring", lambda: None)
    monkeypatch.setattr(tc, "_read_encrypted_file", lambda: None)

    msg = tc.clear_vault_credentials()

    txt = dummy.read_text()
    assert "TOGETHER_API_KEY" not in txt
    assert "OTHER=x" in txt
    assert "removed together_api_key" in msg.lower()
