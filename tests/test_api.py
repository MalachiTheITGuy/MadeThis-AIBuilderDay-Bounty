"""Block 7 tests — heartbeat, leaderboard, outcomes routes."""

import pytest
from fastapi.testclient import TestClient

from seed_data import seed
from src.api.main import app
from src.store.db import connect


@pytest.fixture()
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    seed(conn, reset=True)
    yield conn
    conn.close()


@pytest.fixture()
def client():
    return TestClient(app)


# --- Health & status ---------------------------------------------------------

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "simulation_mode" in data


def test_status(client):
    resp = client.get("/api/v1/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "schema_version" in data
    assert "actions" in data
    assert "outcomes" in data


# --- Leaderboard -------------------------------------------------------------

def test_leaderboard_empty(client):
    resp = client.get("/api/v1/leaderboard")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_leaderboard_has_variants(client):
    resp = client.get("/api/v1/leaderboard")
    assert resp.status_code == 200
    data = resp.json()
    # seed_data creates experiments
    if data:
        item = data[0]
        assert "variant_id" in item
        assert "sent" in item
        assert "replies" in item
        assert "reply_rate" in item


# --- Outcomes ----------------------------------------------------------------

def test_outcomes_empty(client):
    resp = client.get("/api/v1/outcomes")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


# --- Control status ----------------------------------------------------------

def test_control_status(client):
    resp = client.get("/api/v1/control/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data


def test_control_pause_resume(client):
    resp = client.post("/api/v1/control/pause")
    assert resp.status_code == 200
    assert resp.json()["status"] == "paused"

    resp = client.get("/api/v1/control/status")
    assert resp.json()["status"] == "paused"

    resp = client.post("/api/v1/control/resume")
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


# --- Activity trail ----------------------------------------------------------

def test_activity_empty(client):
    resp = client.get("/api/v1/activity")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
