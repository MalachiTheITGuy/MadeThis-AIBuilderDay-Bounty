"""Tests for API authentication (Issue #15).

Note: these tests use monkeypatch to toggle GTM_API_KEY, since config is
loaded at import time.
"""

import pytest
from fastapi.testclient import TestClient


def _client_with_key(monkeypatch, key: str | None):
    import src.api.auth as auth_mod
    import src.api.main as main_mod
    from src.config import SecretStr

    monkeypatch.setattr(auth_mod, "GTM_API_KEY", SecretStr(key))
    # Re-import dependency resolution by rebuilding the TestClient app
    return TestClient(main_mod.app)


def test_auth_open_when_no_key(monkeypatch):
    client = _client_with_key(monkeypatch, None)
    r = client.get("/api/v1/status")
    assert r.status_code == 200


def test_auth_rejects_missing_header(monkeypatch):
    client = _client_with_key(monkeypatch, "secret")
    r = client.get("/api/v1/status")
    assert r.status_code == 401


def test_auth_rejects_wrong_key(monkeypatch):
    client = _client_with_key(monkeypatch, "secret")
    r = client.get("/api/v1/status", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_auth_accepts_correct_key(monkeypatch):
    client = _client_with_key(monkeypatch, "secret")
    r = client.get("/api/v1/status", headers={"X-API-Key": "secret"})
    assert r.status_code == 200


def test_health_stays_open_with_key_set(monkeypatch):
    client = _client_with_key(monkeypatch, "secret")
    r = client.get("/health")
    assert r.status_code == 200
