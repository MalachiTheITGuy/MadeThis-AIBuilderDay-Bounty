"""Tests for multi-touch sequence intelligence (Issue #44, P2-5)."""

import json
import random

import pytest

from seed_data import seed
from src.domain.enums import OutcomeResult
from src.engine.sequences import (
    apply_sequence_outcome,
    get_steps,
    next_step,
    select_sequence,
    step_delay_days,
)
from src.store.db import connect


@pytest.fixture()
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    seed(conn, reset=True)
    yield conn
    conn.close()


def _seed_opp(conn, opp_id="opp-seq", contact_id="p-acme-ceo"):
    if not conn.execute("SELECT 1 FROM signals WHERE id = 'sig-seq'").fetchone():
        conn.execute(
            "INSERT INTO signals (id, company_id, type, payload, detected_at) "
            "VALUES ('sig-seq', 'c-acme', 'FUNDING', '{}', '2026-01-15T10:00:00')"
        )
    conn.execute(
        "INSERT OR IGNORE INTO opportunities (id, company_id, signal_id, status, score, pipeline_stage) "
        "VALUES (?, 'c-acme', 'sig-seq', 'QUALIFIED', 0.8, 'QUALIFIED')",
        (opp_id,),
    )
    conn.commit()


def _seed_action(conn, action_id="a1", opp_id="opp-seq", sequence_id="seq-saas-email",
                 step_index=1, status="SENT"):
    _seed_opp(conn, opp_id)
    conn.execute(
        "INSERT INTO actions (id, opportunity_id, contact_id, action_type, variant_id, "
        "channel, timing, mode, status, subject, body, cost_units, policy_version, sequence_id, step_index) "
        "VALUES (?, ?, 'p-acme-ceo', 'OUTREACH_EMAIL', 'v-saas-email-warm-morning', "
        "'EMAIL', 'MORNING', 'AUTOPILOT', ?, 'Test', 'Hello', 1, 1, ?, ?)",
        (action_id, opp_id, status, sequence_id, step_index),
    )
    conn.commit()


def _seed_outcome(conn, action_id, result):
    conn.execute(
        "INSERT INTO outcomes (id, action_id, result, detail, at) "
        "VALUES (?, ?, ?, '', '2026-08-13T10:00:00')",
        (f"out-{action_id}", action_id, result.value),
    )
    conn.commit()


def test_seed_has_sequences(db):
    rows = db.execute("SELECT COUNT(*) AS n FROM sequences").fetchone()
    assert rows["n"] > 0
    steps = db.execute("SELECT COUNT(*) AS n FROM sequence_steps").fetchone()
    assert steps["n"] > 0


def test_select_sequence_thompson(db):
    conn = db
    rng = random.Random(42)
    seq = select_sequence(conn, "saas-b2b", rng)
    assert seq["sequence_id"] in ("seq-saas-email", "seq-saas-cross")
    assert "stats" in seq
    # Deterministic with same seed
    seq2 = select_sequence(conn, "saas-b2b", random.Random(42))
    assert seq2["sequence_id"] == seq["sequence_id"]


def test_next_step_starts_at_one(db):
    conn = db
    step = next_step(conn, "seq-saas-email", "opp-seq")
    assert step is not None
    assert step["step_order"] == 1


def test_no_response_advances_to_step_2(db):
    conn = db
    _seed_action(conn, action_id="a1", step_index=1)
    _seed_outcome(conn, "a1", OutcomeResult.NO_RESPONSE)
    step = next_step(conn, "seq-saas-email", "opp-seq")
    assert step is not None
    assert step["step_order"] == 2


def test_reply_stops_sequence_and_upgrades_warmth(db):
    conn = db
    _seed_action(conn, action_id="a1", step_index=1)
    _seed_outcome(conn, "a1", OutcomeResult.REPLY)
    result = apply_sequence_outcome(conn, "a1", OutcomeResult.REPLY)
    assert result["stopped"] is True
    assert result["warmth_upgraded"] is True
    # No further steps scheduled (stop rule reads the REPLY outcome)
    assert next_step(conn, "seq-saas-email", "opp-seq") is None
    # Warmth upgraded
    warmth = conn.execute(
        "SELECT warmth FROM contacts WHERE id = 'p-acme-ceo'"
    ).fetchone()["warmth"]
    assert warmth == "replied"


def test_no_response_updates_sequence_stats(db):
    conn = db
    _seed_action(conn, action_id="a1", step_index=1)
    result = apply_sequence_outcome(conn, "a1", OutcomeResult.NO_RESPONSE)
    assert result["advanced"] is True
    stats = json.loads(
        conn.execute(
            "SELECT stats FROM sequences WHERE sequence_id = 'seq-saas-email'"
        ).fetchone()["stats"]
    )
    assert stats["sent"] == 1


def test_last_step_no_response_ends_sequence(db):
    conn = db
    # Step 3 is the last step of seq-saas-email
    _seed_action(conn, action_id="a3", step_index=3)
    result = apply_sequence_outcome(conn, "a3", OutcomeResult.NO_RESPONSE)
    assert result["advanced"] is False
    assert result["stopped"] is True
    assert next_step(conn, "seq-saas-email", "opp-seq") is None


def test_policy_timing_adjustment_changes_step_spacing(db):
    conn = db
    base = step_delay_days(conn, "seq-saas-email", 2)
    assert base == 3  # seed delay_days=3, timing_prior_adjustment=0

    # Negative adjustment → tighter cadence (min 1 day)
    conn.execute(
        "INSERT INTO policies (version, policy, source) VALUES (2, ?, 'rejection:bad_timing')",
        (json.dumps({"timing_prior_adjustment": -0.4}),),
    )
    conn.commit()
    tightened = step_delay_days(conn, "seq-saas-email", 2)
    assert tightened < base

    # Positive adjustment → looser cadence
    conn.execute(
        "INSERT INTO policies (version, policy, source) VALUES (3, ?, 'rejection:bad_timing')",
        (json.dumps({"timing_prior_adjustment": 0.5}),),
    )
    conn.commit()
    loosened = step_delay_days(conn, "seq-saas-email", 2)
    assert loosened > base


def test_sequences_endpoint(tmp_path, monkeypatch):
    import src.config as config_mod
    # Point the store at a fresh seeded DB before the app resolves it
    from src.store import db as db_mod
    db_path = tmp_path / "endpoint.db"
    monkeypatch.setattr(config_mod, "DB_PATH", str(db_path))
    monkeypatch.setattr(db_mod, "DB_PATH", str(db_path))
    seed(db_mod.connect(), reset=True)

    from fastapi.testclient import TestClient
    from src.api.main import app

    client = TestClient(app)
    resp = client.get("/api/v1/sequences")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) > 0
    saas = next(r for r in rows if r["sequence_id"] == "seq-saas-email")
    assert saas["max_steps"] == 3
    assert "OUTREACH_EMAIL:EMAIL:0" in saas["steps"]
    assert "stats" in saas
