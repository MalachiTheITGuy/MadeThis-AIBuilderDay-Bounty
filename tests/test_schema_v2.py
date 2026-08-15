"""Tests for schema v2 migration (P0-3: Issue #34)."""

import pytest
from src.store.db import connect, current_version, SCHEMA_VERSION


class TestSchemaV2:
    def test_migration_v2_adds_columns(self):
        """v2 migration adds segment, expected_effect, confidence to actions."""
        db = connect(":memory:")
        assert current_version(db) == SCHEMA_VERSION

        # Verify new columns exist
        cols = {row[1] for row in db.execute("PRAGMA table_info(actions)").fetchall()}
        assert "segment" in cols
        assert "expected_effect" in cols
        assert "confidence" in cols
        db.close()

    def test_schema_version_is_current(self):
        """SCHEMA_VERSION constant is updated."""
        from src.store.db import SCHEMA_VERSION as current
        assert SCHEMA_VERSION >= 2
        assert SCHEMA_VERSION == current

    def test_migration_v3_adds_revenue_columns(self):
        """v3 migration adds revenue attribution columns to opportunities."""
        db = connect(":memory:")
        assert current_version(db) == SCHEMA_VERSION
        cols = {row[1] for row in db.execute("PRAGMA table_info(opportunities)").fetchall()}
        assert "won_at" in cols
        assert "arr" in cols
        assert "pipeline_stage" in cols
        db.close()

    def test_status_endpoint_includes_frontend_fields(self):
        """GET /api/v1/status returns fields the React frontend expects."""
        from fastapi.testclient import TestClient
        from src.api.main import app

        client = TestClient(app)
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200
        data = resp.json()
        # Frontend SystemStatus fields
        assert "mode" in data
        assert "paused" in data
        assert "stopped" in data
        assert "queue_count" in data
        assert "active_opportunities" in data
        assert "today_sent" in data
        assert "today_budget_used" in data
        # Existing fields
        assert "schema_version" in data
        assert "simulation_mode" in data

    def test_queue_serializes_decision_trace(self):
        """GET /api/v1/queue returns decision_trace as object, not string."""
        from fastapi.testclient import TestClient
        from src.api.main import app

        client = TestClient(app)
        resp = client.get("/api/v1/queue")
        assert resp.status_code == 200
        for action in resp.json():
            assert isinstance(action.get("decision_trace"), dict)
            assert isinstance(action.get("guardrail_blocks"), list)
