"""LEARN tests (PLAN.md task D7) — the five behavior-change tests."""

import json

import pytest

from seed_data import seed
from src.domain.enums import OutcomeResult, RejectionReason
from src.domain.models import Outcome
from src.engine.learn import apply_feedback, apply_outcome, rollback_policy
from src.store.db import connect


@pytest.fixture()
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    seed(conn, reset=True)
    yield conn
    conn.close()


def _seed_action(conn, action_id="act-learn-1", variant_id="v-saas-email-warm-morning",
                 contact_id="p-acme-ceo", status="SENT"):
    """Insert a test action with required FK parents."""
    if not conn.execute("SELECT 1 FROM signals WHERE id = 'sig-test'").fetchone():
        conn.execute(
            "INSERT INTO signals (id, company_id, type, payload, detected_at) "
            "VALUES ('sig-test', 'c-acme', 'FUNDING', '{}', '2026-01-15T10:00:00')"
        )
    if not conn.execute("SELECT 1 FROM opportunities WHERE id = 'opp-test'").fetchone():
        conn.execute(
            "INSERT INTO opportunities (id, company_id, signal_id, status, score) "
            "VALUES ('opp-test', 'c-acme', 'sig-test', 'QUALIFIED', 0.8)"
        )
    conn.execute(
        "INSERT INTO actions (id, opportunity_id, contact_id, action_type, variant_id, "
        "channel, timing, mode, status, subject, body, cost_units, policy_version) "
        "VALUES (?, 'opp-test', ?, 'OUTREACH_EMAIL', ?, 'EMAIL', 'MORNING', 'PROPOSE', ?, 'Test', 'Hello', 1, 1)",
        (action_id, contact_id, variant_id, status),
    )
    conn.commit()


def _get_stats(conn, variant_id):
    """Get variant stats as dict."""
    row = conn.execute(
        "SELECT stats FROM experiments WHERE variant_id = ?",
        (variant_id,),
    ).fetchone()
    return json.loads(row["stats"]) if row else {}


def _get_policy(conn):
    """Get latest policy."""
    row = conn.execute(
        "SELECT version, policy FROM policies ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return {"version": row["version"], "policy": json.loads(row["policy"])}


# ---------------------------------------------------------------------------
# Test 1: Outcome updates variant stats (§4.4.4)
# ---------------------------------------------------------------------------

def test_outcome_updates_variant_stats(db):
    """Feed outcomes favoring a variant → assert stats changed."""
    variant = "v-saas-email-warm-morning"
    _seed_action(db, action_id="act-out-1", variant_id=variant)

    initial_stats = _get_stats(db, variant)
    initial_sent = initial_stats.get("sent", 0)

    outcome = Outcome(action_id="act-out-1", result=OutcomeResult.REPLY, detail="warm reply")
    delta = apply_outcome(db, outcome)

    updated_stats = _get_stats(db, variant)
    assert updated_stats["sent"] == initial_sent + 1
    assert updated_stats.get("replies", 0) == 1
    assert "REPLY" in str(delta.variant_updates)


# ---------------------------------------------------------------------------
# Test 2: Reject with reason → policy changes (§4.4.2)
# ---------------------------------------------------------------------------

def test_reject_too_salesy_moves_tone(db):
    """Reject draft with reason 'too_salesy' → assert tone moved."""
    _seed_action(db, action_id="act-rej-1")

    initial_policy = _get_policy(db)
    initial_tone = initial_policy["policy"].get("tone_assertiveness", 0.5)

    delta = apply_feedback(db, "act-rej-1", reason=RejectionReason.TOO_SALESY.value)

    updated_policy = _get_policy(db)
    updated_tone = updated_policy["policy"].get("tone_assertiveness", 0.5)
    assert updated_tone < initial_tone
    assert updated_policy["version"] > initial_policy["version"]
    assert any(d.field == "tone_assertiveness" for d in delta.policy_deltas)


def test_reject_too_long_increases_brevity(db):
    """Reject draft with reason 'too_long' → assert brevity increased."""
    _seed_action(db, action_id="act-rej-2")

    initial_policy = _get_policy(db)
    initial_brevity = initial_policy["policy"].get("brevity", 0.0)

    apply_feedback(db, "act-rej-2", reason=RejectionReason.TOO_LONG.value)

    updated_policy = _get_policy(db)
    updated_brevity = updated_policy["policy"].get("brevity", 0.0)
    assert updated_brevity > initial_brevity


def test_reject_missing_personalization_increases_depth(db):
    """Reject draft with reason 'missing_personalization' → assert depth increased."""
    _seed_action(db, action_id="act-rej-3")

    initial_policy = _get_policy(db)
    initial_depth = initial_policy["policy"].get("personalization_depth", 1)

    apply_feedback(db, "act-rej-3", reason=RejectionReason.MISSING_PERSONALIZATION.value)

    updated_policy = _get_policy(db)
    updated_depth = updated_policy["policy"].get("personalization_depth", 1)
    assert updated_depth > initial_depth


# ---------------------------------------------------------------------------
# Test 3: Edit a draft → personalization increases (§4.4.3)
# ---------------------------------------------------------------------------

def test_edit_increases_personalization(db):
    """Edit draft to add personal details → assert personalization_depth increased."""
    _seed_action(db, action_id="act-edit-1")

    initial_policy = _get_policy(db)
    initial_depth = initial_policy["policy"].get("personalization_depth", 1)

    delta = apply_feedback(db, "act-edit-1", edits={"personalization_count": 2})

    updated_policy = _get_policy(db)
    updated_depth = updated_policy["policy"].get("personalization_depth", 1)
    assert updated_depth == initial_depth + 2
    assert delta.playbook_new_version > 0


# ---------------------------------------------------------------------------
# Test 4: Rollback reverts policy (§4.4.5)
# ---------------------------------------------------------------------------

def test_rollback_reverts_policy(db):
    """Mutate policy, call rollback → assert policy_version reverted."""
    _seed_action(db, action_id="act-rb-1")

    # Apply a mutation
    apply_feedback(db, "act-rb-1", reason=RejectionReason.TOO_SALESY.value)
    policy_after_mutation = _get_policy(db)
    version_after_mutation = policy_after_mutation["version"]

    # Rollback
    restored_version = rollback_policy(db)
    policy_after_rollback = _get_policy(db)

    assert restored_version == version_after_mutation + 1
    assert policy_after_rollback["version"] == restored_version
    # The policy content should match the pre-mutation version
    policy_before = db.execute(
        "SELECT policy FROM policies WHERE version = ?",
        (version_after_mutation - 1,),
    ).fetchone()
    assert policy_after_rollback["policy"] == json.loads(policy_before["policy"])


def test_rollback_no_op_when_at_version_1(db):
    """Rollback at version 1 → no-op, returns 0."""
    result = rollback_policy(db)
    assert result == 0


# ---------------------------------------------------------------------------
# Warm-graph updates
# ---------------------------------------------------------------------------

def test_positive_outcome_strengthens_warm_edge(db):
    """Positive outcome → warm edge strength increases."""
    _seed_action(db, action_id="act-warm-1", contact_id="p-acme-ceo")

    outcome = Outcome(action_id="act-warm-1", result=OutcomeResult.REPLY, detail="replied")
    delta = apply_outcome(db, outcome)

    assert len(delta.warm_graph_deltas) == 1
    assert delta.warm_graph_deltas[0].strength_delta > 0


def test_negative_outcome_weakens_warm_edge(db):
    """Negative outcome → warm edge strength decreases."""
    _seed_action(db, action_id="act-warm-2", contact_id="p-acme-ceo")

    outcome = Outcome(action_id="act-warm-2", result=OutcomeResult.UNSUB, detail="unsubscribed")
    delta = apply_outcome(db, outcome)

    assert len(delta.warm_graph_deltas) == 1
    assert delta.warm_graph_deltas[0].strength_delta < 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_unknown_action_returns_empty_delta(db):
    """Feedback on nonexistent action → empty delta."""
    delta = apply_feedback(db, "nonexistent", reason="too_salesy")
    assert delta.policy_deltas == []
    assert delta.playbook_new_version == 0


def test_unknown_reason_returns_empty_delta(db):
    """Feedback with unknown reason → empty delta."""
    _seed_action(db, action_id="act-edge-1")
    delta = apply_feedback(db, "act-edge-1", reason="some_unknown_reason")
    assert delta.policy_deltas == []
