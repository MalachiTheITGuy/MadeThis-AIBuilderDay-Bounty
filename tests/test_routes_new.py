"""Smoke tests for all new API routes (P0-2: Issue #33)."""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

import src.config as cfg
from seed_data import seed
from src.api.main import app


@pytest.fixture(autouse=True)
def _seed_db(tmp_path):
    """Seed a temp-file DB so the API routes see the same data."""
    db_path = str(tmp_path / "test.db")
    os.environ["GTM_DB_PATH"] = db_path
    # Patch the DB_PATH in db.py so connect() uses the temp DB
    import src.store.db as _db
    _orig = _db.DB_PATH
    _db.DB_PATH = db_path

    from src.store.db import connect
    conn = connect(db_path)
    seed(conn)
    conn.close()
    yield
    _db.DB_PATH = _orig
    cfg.DB_PATH = os.environ.pop("GTM_DB_PATH", "gtm-loop.db")


@pytest.fixture()
def client():
    return TestClient(app)


class TestCompanies:
    def test_get_companies(self, client):
        resp = client.get("/api/v1/companies")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        assert "id" in data[0]
        assert "name" in data[0]
        assert "tags" in data[0]


class TestContacts:
    def test_get_contacts(self, client):
        resp = client.get("/api/v1/contacts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        assert "company_id" in data[0]

    def test_get_contacts_by_company(self, client):
        companies = client.get("/api/v1/companies").json()
        cid = companies[0]["id"]
        resp = client.get(f"/api/v1/contacts?company_id={cid}")
        assert resp.status_code == 200
        for c in resp.json():
            assert c["company_id"] == cid


class TestVariants:
    def test_get_variants(self, client):
        resp = client.get("/api/v1/variants")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        assert "id" in data[0]
        assert "stats" in data[0]

    def test_create_variant(self, client):
        resp = client.post("/api/v1/variants", json={
            "variant_id": "test-variant-new",
            "segment": "saas-b2b",
            "template": "Hi {name}, test template",
            "channel": "EMAIL",
            "timing": "MORNING",
            "tone": "warm",
            "personalization_depth": 1,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "test-variant-new"
        assert data["stats"]["sent"] == 0

    def test_update_variant(self, client):
        client.post("/api/v1/variants", json={
            "variant_id": "test-variant-upd",
            "segment": "saas-b2b",
            "template": "original",
            "channel": "EMAIL",
            "timing": "MORNING",
            "tone": "warm",
            "personalization_depth": 1,
        })
        resp = client.patch("/api/v1/variants/test-variant-upd", json={
            "template": "updated template",
        })
        assert resp.status_code == 200
        assert resp.json()["template"] == "updated template"


class TestPolicy:
    def test_get_policy(self, client):
        resp = client.get("/api/v1/policy")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert "brevity" in data

    def test_update_policy(self, client):
        resp = client.patch("/api/v1/policy", json={"brevity": 0.8})
        assert resp.status_code == 200
        data = resp.json()
        assert data["brevity"] == 0.8
        assert data["version"] >= 2

    def test_rollback_policy(self, client):
        # Create v2
        client.patch("/api/v1/policy", json={"brevity": 0.9})
        resp = client.post("/api/v1/policy/rollback/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] >= 3


class TestWarmGraph:
    def test_get_warm_graph(self, client):
        resp = client.get("/api/v1/warm-graph")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_update_warm_edge(self, client):
        edges = client.get("/api/v1/warm-graph").json()
        if edges:
            eid = edges[0]["id"]
            resp = client.patch(f"/api/v1/warm-graph/{eid}", json={"strength": 0.99})
            assert resp.status_code == 200
            assert resp.json()["strength"] == 0.99


class TestOutcomes:
    def test_record_outcome(self, client):
        from src.store.db import connect
        from datetime import UTC, datetime
        conn = connect()
        try:
            contact = conn.execute("SELECT id, company_id FROM contacts LIMIT 1").fetchone()
            # Insert a signal first (FK required)
            conn.execute(
                "INSERT INTO signals (id, company_id, type, payload, detected_at) "
                "VALUES ('sig-test', ?, 'FUNDING', '{}', ?)",
                (contact["company_id"], datetime.now(UTC).isoformat()),
            )
            conn.execute(
                "INSERT INTO opportunities (id, company_id, signal_id, status, score, fit_notes, decision_trace) "
                "VALUES ('opp-test-o', ?, 'sig-test', 'QUALIFIED', 0.8, '[]', '{}')",
                (contact["company_id"],),
            )
            conn.execute(
                "INSERT INTO actions (id, opportunity_id, contact_id, action_type, variant_id, "
                "channel, timing, mode, status, subject, body, cost_units, policy_version) "
                "VALUES ('act-test-o', 'opp-test-o', ?, 'OUTREACH_EMAIL', 'v-saas-email-warm-morning', "
                "'EMAIL', 'MORNING', 'PROPOSE', 'PROPOSED', 'test', 'body', 1, 1)",
                (contact["id"],),
            )
            conn.commit()
        finally:
            conn.close()

        resp = client.post("/api/v1/outcomes", json={
            "action_id": "act-test-o",
            "result": "REPLY",
            "detail": "test reply",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"] == "REPLY"


class TestControlMode:
    def test_set_mode_propose(self, client):
        resp = client.post("/api/v1/control/mode", json={"mode": "PROPOSE"})
        assert resp.status_code == 200
        assert resp.json()["mode"] == "PROPOSE"

    def test_set_mode_autopilot(self, client):
        resp = client.post("/api/v1/control/mode", json={"mode": "AUTOPILOT"})
        assert resp.status_code == 200
        assert resp.json()["mode"] == "AUTOPILOT"
        assert resp.json()["scope"]["enabled"] is True

    def test_invalid_mode(self, client):
        resp = client.post("/api/v1/control/mode", json={"mode": "INVALID"})
        assert resp.status_code == 400


class TestControlScope:
    def test_set_scope(self, client):
        resp = client.post("/api/v1/control/scope", json={
            "allowed_segments": ["saas-b2b"],
            "max_cost_units_per_action": 2,
        })
        assert resp.status_code == 200
        scope = resp.json()["scope"]
        assert scope["allowed_segments"] == ["saas-b2b"]
        assert scope["max_cost_units_per_action"] == 2

    def test_scope_persists(self, client):
        client.post("/api/v1/control/scope", json={"max_sends_per_day": 5})
        resp = client.post("/api/v1/control/scope", json={"allowed_channels": ["EMAIL"]})
        scope = resp.json()["scope"]
        assert scope["max_sends_per_day"] == 5
        assert scope["allowed_channels"] == ["EMAIL"]
