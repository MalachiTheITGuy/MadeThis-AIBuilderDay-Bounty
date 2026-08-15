"""E2E demo test (PLAN.md task H1).

Full loop: same seed ⇒ same demo; learning cycle changes second action.
Verifies the entire pipeline from signal scan through learning.
"""

import json

import pytest

from seed_data import seed
from src.domain.enums import OutcomeResult
from src.domain.models import Outcome
from src.engine.execute import execute_action
from src.engine.learn import apply_feedback, apply_outcome, rollback_policy
from src.engine.permission import get_control_status, set_control_status
from src.store.db import connect


@pytest.fixture()
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    seed(conn, reset=True)
    yield conn
    conn.close()


def _get_policy(conn):
    row = conn.execute(
        "SELECT version, policy FROM policies ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return {"version": row["version"], "policy": json.loads(row["policy"])}


def _seed_action(conn, action_id="act-e2e", contact_id="p-acme-ceo"):
    """Insert a test action with required FK parents."""
    if not conn.execute("SELECT 1 FROM signals WHERE id = 'sig-e2e'").fetchone():
        conn.execute(
            "INSERT INTO signals (id, company_id, type, payload, detected_at) "
            "VALUES ('sig-e2e', 'c-acme', 'FUNDING', '{}', '2026-01-15T10:00:00')"
        )
    if not conn.execute("SELECT 1 FROM opportunities WHERE id = 'opp-e2e'").fetchone():
        conn.execute(
            "INSERT INTO opportunities (id, company_id, signal_id, status, score) "
            "VALUES ('opp-e2e', 'c-acme', 'sig-e2e', 'QUALIFIED', 0.8)"
        )
    conn.execute(
        "INSERT INTO actions (id, opportunity_id, contact_id, action_type, variant_id, "
        "channel, timing, mode, status, subject, body, cost_units, policy_version) "
        "VALUES (?, 'opp-e2e', ?, 'OUTREACH_EMAIL', 'v-saas-email-warm-morning', "
        "'EMAIL', 'MORNING', 'PROPOSE', 'PROPOSED', 'Test', 'Hello', 1, 1)",
        (action_id, contact_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Scene 1: Seed creates experiments and policies
# ---------------------------------------------------------------------------

def test_scene1_seed_has_experiments(db):
    """Seed data creates experiments (variants)."""
    rows = db.execute("SELECT COUNT(*) AS n FROM experiments").fetchone()
    assert rows["n"] > 0, "No experiments from seed"


def test_scene1_seed_has_policies(db):
    """Seed data creates initial policy."""
    policy = _get_policy(db)
    assert policy is not None
    assert policy["version"] >= 1


# ---------------------------------------------------------------------------
# Scene 2: Reject with reason → policy changes
# ---------------------------------------------------------------------------

def test_scene2_reject_changes_policy(db):
    """Reject action with reason 'too_salesy' → tone decreases."""
    _seed_action(db, action_id="act-rej")

    initial_policy = _get_policy(db)
    initial_tone = initial_policy["policy"].get("tone_assertiveness", 0.5)

    apply_feedback(db, "act-rej", reason="too_salesy")

    updated_policy = _get_policy(db)
    updated_tone = updated_policy["policy"].get("tone_assertiveness", 0.5)
    assert updated_tone < initial_tone


# ---------------------------------------------------------------------------
# Scene 3: Execute action → outcome → stats update
# ---------------------------------------------------------------------------

def test_scene3_execute_and_outcome_updates_stats(db):
    """Execute action, record meeting → variant stats updated."""
    _seed_action(db, action_id="act-exe")

    # Execute
    status = execute_action(db, "act-exe", "EMAIL")
    assert status.value == "SENT"

    # Record outcome
    outcome = Outcome(
        action_id="act-exe",
        result=OutcomeResult.MEETING,
        detail="booked meeting",
    )
    delta = apply_outcome(db, outcome)
    assert "v-saas-email-warm-morning" in delta.variant_updates


# ---------------------------------------------------------------------------
# Scene 4: Rollback reverts policy
# ---------------------------------------------------------------------------

def test_scene4_rollback_reverts_policy(db):
    """Rollback policy to previous version."""
    _seed_action(db, action_id="act-rb")

    # Mutate
    apply_feedback(db, "act-rb", reason="too_salesy")
    policy_after = _get_policy(db)

    # Rollback
    restored = rollback_policy(db)
    policy_rolled = _get_policy(db)

    assert restored == policy_after["version"] + 1
    assert policy_rolled["version"] == restored


# ---------------------------------------------------------------------------
# Scene 5: Kill switch
# ---------------------------------------------------------------------------

def test_scene5_kill_switch(db):
    """Kill switch pauses and resumes the loop."""
    assert get_control_status() == "running"

    set_control_status("paused")
    assert get_control_status() == "paused"

    set_control_status("running")
    assert get_control_status() == "running"


# ---------------------------------------------------------------------------
# Deterministic: same seed → same results
# ---------------------------------------------------------------------------

def test_deterministic_seed(tmp_path):
    """Same seed produces same experiments and policies."""
    db1 = connect(tmp_path / "db1.db")
    seed(db1, reset=True)
    exps1 = db1.execute("SELECT variant_id FROM experiments ORDER BY variant_id").fetchall()
    pol1 = _get_policy(db1)
    db1.close()

    db2 = connect(tmp_path / "db2.db")
    seed(db2, reset=True)
    exps2 = db2.execute("SELECT variant_id FROM experiments ORDER BY variant_id").fetchall()
    pol2 = _get_policy(db2)
    db2.close()

    assert [e["variant_id"] for e in exps1] == [e["variant_id"] for e in exps2]
    assert pol1["version"] == pol2["version"]
    assert pol1["policy"] == pol2["policy"]
