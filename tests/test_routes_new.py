"""Smoke tests for all new API routes (P0-2: Issue #33)."""

import os
import tempfile
from datetime import UTC, datetime

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
    conn.execute(
        "INSERT INTO signals (id, company_id, type, payload, detected_at) "
        "VALUES ('sig-api-opportunity', 'c-acme', 'FUNDING', '{\"amount\":\"$5M\"}', ?)",
        (datetime.now(UTC).isoformat(),),
    )
    conn.execute(
        "INSERT INTO opportunities (id, company_id, signal_id, status, score, fit_notes, decision_trace) "
        "VALUES ('opp-api-opportunity', 'c-acme', 'sig-api-opportunity', 'QUALIFIED', 0.9, '[\"funding signal\"]', '{}')"
    )
    conn.execute(
        "INSERT INTO actions (id, opportunity_id, contact_id, action_type, variant_id, channel, timing, mode, status, subject, body, cost_units, policy_version) "
        "VALUES ('act-api-opportunity', 'opp-api-opportunity', 'p-acme-ceo', 'OUTREACH_EMAIL', 'v-saas-email-warm-morning', 'EMAIL', 'MORNING', 'PROPOSE', 'PROPOSED', 'Test subject', 'Test body', 1, 1)"
    )
    conn.commit()
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

    def test_get_scope(self, client):
        client.post("/api/v1/control/scope", json={"allowed_segments": ["saas-b2b"]})
        resp = client.get("/api/v1/control/scope")
        assert resp.status_code == 200
        assert resp.json()["scope"]["allowed_segments"] == ["saas-b2b"]


class TestSettingsPreferences:
    def test_application_settings_defaults_and_update(self, client):
        initial = client.get("/api/v1/settings/application")
        assert initial.status_code == 200
        assert initial.json()["settings"]["theme"] == "system"

        updated = client.patch("/api/v1/settings/application", json={
            "theme": "dark",
            "density": "compact",
            "refresh_interval_seconds": 30,
        })
        assert updated.status_code == 200
        assert updated.json()["settings"]["theme"] == "dark"
        assert client.get("/api/v1/settings/application").json()["settings"]["density"] == "compact"

    def test_application_reset_only_resets_preferences(self, client):
        client.patch("/api/v1/settings/application", json={"theme": "dark"})
        reset = client.post("/api/v1/settings/application/reset")
        assert reset.status_code == 200
        assert reset.json()["reset"] is True
        assert reset.json()["settings"]["theme"] == "system"
        assert client.get("/api/v1/companies").json()

    def test_application_validation(self, client):
        resp = client.patch("/api/v1/settings/application", json={"refresh_interval_seconds": 2})
        assert resp.status_code == 422

    def test_workspace_settings_persist(self, client):
        updated = client.patch("/api/v1/settings/workspace", json={
            "name": "Growth workspace",
            "timezone": "America/Denver",
            "default_currency": "USD",
        })
        assert updated.status_code == 200
        settings = client.get("/api/v1/settings/workspace").json()["settings"]
        assert settings["name"] == "Growth workspace"
        assert settings["timezone"] == "America/Denver"

    def test_settings_changes_are_audited(self, client):
        client.patch("/api/v1/settings/workspace", json={"name": "Audited workspace"})
        events = client.get("/api/v1/activity", params={"event": "workspace_settings_update"}).json()
        assert events
        assert events[0]["detail"]


class TestLLMSettings:
    def test_create_test_and_activate_local_provider(self, client):
        created = client.post("/api/v1/settings/llm/providers", json={
            "name": "Local model",
            "kind": "local",
            "base_url": "local://model",
            "model": "demo-model",
            "capabilities": {"chat": True},
        })
        assert created.status_code == 200
        provider = created.json()["provider"]
        assert provider["api_key"] is None
        assert provider["api_key_configured"] is True

        tested = client.post(f"/api/v1/settings/llm/providers/{provider['provider_id']}/test")
        assert tested.status_code == 200
        assert tested.json()["healthy"] is True

        active = client.put("/api/v1/settings/llm/active", json={"provider_id": provider["provider_id"]})
        assert active.status_code == 200
        assert client.get("/api/v1/settings/llm/active").json()["provider"]["provider_id"] == provider["provider_id"]

    def test_remote_provider_without_secret_is_not_healthy(self, client):
        created = client.post("/api/v1/settings/llm/providers", json={
            "name": "Remote model",
            "kind": "openai_compatible",
            "base_url": "https://provider.example/v1",
            "model": "remote-model",
            "api_key_env_var": "MISSING_LLM_KEY",
        })
        provider_id = created.json()["provider"]["provider_id"]
        tested = client.post(f"/api/v1/settings/llm/providers/{provider_id}/test")
        assert tested.status_code == 200
        assert tested.json()["healthy"] is False
        assert client.put("/api/v1/settings/llm/active", json={"provider_id": provider_id}).status_code == 409

    def test_provider_secret_never_returns(self, client):
        created = client.post("/api/v1/settings/llm/providers", json={
            "name": "Local secret test",
            "kind": "local",
            "base_url": "local://model",
            "model": "demo-model",
            "api_key_env_var": "LLM_API_KEY",
        })
        assert created.status_code == 200
        assert created.json()["provider"]["api_key"] is None
        listed = client.get("/api/v1/settings/llm/providers").json()["providers"]
        assert all(item.get("api_key") is None for item in listed)


class TestOperatorResources:
    def test_get_opportunities(self, client):
        resp = client.get("/api/v1/opportunities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0
        assert data["items"]
        assert "company" in data["items"][0]
        assert "signal" in data["items"][0]
        assert "current_action" in data["items"][0]

    def test_get_opportunity_detail(self, client):
        opportunity = client.get("/api/v1/opportunities").json()["items"][0]
        resp = client.get(f"/api/v1/opportunities/{opportunity['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == opportunity["id"]
        assert "signal_timeline" in data
        assert "relationship_edges" in data
        assert "what_would_change_this" in data

    def test_opportunity_filters(self, client):
        resp = client.get("/api/v1/opportunities", params={"signal_type": "FUNDING", "limit": 1})
        assert resp.status_code == 200
        assert all(item["signal"]["type"] == "FUNDING" for item in resp.json()["items"])

    def test_learning_changes_and_policy_history(self, client):
        changes = client.get("/api/v1/learning/changes")
        history = client.get("/api/v1/policy/history")
        assert changes.status_code == 200
        assert history.status_code == 200
        assert changes.json()["active_policy_version"] >= 1
        assert history.json()[0]["version"] == 1

    def test_action_timeline(self, client):
        resp = client.get("/api/v1/actions/act-api-opportunity/timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["stages"]) == 9
        assert data["stages"][0]["name"] == "Signal"

    def test_missing_opportunity_is_404(self, client):
        resp = client.get("/api/v1/opportunities/not-found")
        assert resp.status_code == 404


class TestDecisionMutations:
    def test_approve_without_note(self, client):
        resp = client.post("/api/v1/decisions/act-api-opportunity/approve", json={})
        assert resp.status_code == 200
        assert resp.json() == {"status": "approved", "action_id": "act-api-opportunity", "reason": None}

    def test_approve_with_note_records_activity(self, client):
        resp = client.post(
            "/api/v1/decisions/act-api-opportunity/approve",
            json={"note": "Keep the funding angle"},
        )
        assert resp.status_code == 200
        activity = client.get("/api/v1/activity", params={"event": "approve"}).json()
        assert any(item["action_id"] == "act-api-opportunity" and item["detail"] == "Keep the funding angle" for item in activity)

    def test_duplicate_approval_is_rejected(self, client):
        first = client.post("/api/v1/decisions/act-api-opportunity/approve", json={})
        second = client.post("/api/v1/decisions/act-api-opportunity/approve", json={})
        assert first.status_code == 200
        assert second.status_code == 400

    def test_approve_missing_action_is_404(self, client):
        resp = client.post("/api/v1/decisions/missing/approve", json={})
        assert resp.status_code == 404
