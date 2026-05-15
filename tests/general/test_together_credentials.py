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
