"""Tests for the heartbeat tick pipeline (P0-1: Issue #32)."""

import json
import uuid
from datetime import UTC, datetime

import pytest


@pytest.fixture()
def db():
    from src.store.db import connect
    conn = connect(":memory:")
    yield conn
    conn.close()


class TestHeartbeatTick:
    def test_tick_creates_actions_from_seed(self, db):
        """Seed data → run tick → opportunities created, actions proposed."""
        from seed_data import seed
        seed(db)
        from src.engine.permission import set_control_status
        set_control_status("running")

        import asyncio
        from src.api.main import _heartbeat_tick
        asyncio.run(_heartbeat_tick(db))

        # Check opportunities were created
        opps = db.execute("SELECT * FROM opportunities").fetchall()
        assert len(opps) > 0, "Expected opportunities to be created"

        # Check actions were proposed
        actions = db.execute("SELECT * FROM actions").fetchall()
        assert len(actions) > 0, "Expected actions to be proposed"
        for a in actions:
            assert a["status"] in ("PROPOSED", "EXECUTED")
            assert a["subject"] is not None
            assert a["body"] is not None

    def test_tick_respects_paused(self, db):
        """Tick should do nothing when paused."""
        from seed_data import seed
        seed(db)
        from src.engine.permission import set_control_status
        set_control_status("paused")

        import asyncio
        from src.api.main import _heartbeat_tick
        asyncio.run(_heartbeat_tick(db))

        opps = db.execute("SELECT * FROM opportunities").fetchall()
        assert len(opps) == 0, "No opportunities should be created when paused"

    def test_tick_deduplicates_opportunities(self, db):
        """Running tick twice should not create duplicate actions for same opportunity."""
        from seed_data import seed
        seed(db)
        from src.engine.permission import set_control_status
        set_control_status("running")

        import asyncio
        from src.api.main import _heartbeat_tick
        asyncio.run(_heartbeat_tick(db))
        actions_first = db.execute("SELECT COUNT(*) AS n FROM actions").fetchone()["n"]

        asyncio.run(_heartbeat_tick(db))
        actions_second = db.execute("SELECT COUNT(*) AS n FROM actions").fetchone()["n"]

        # Actions should not double — deduplication prevents re-proposing
        assert actions_second == actions_first, (
            f"Expected no new actions on second tick, got {actions_first} → {actions_second}"
        )
