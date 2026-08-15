"""PERMISSION + PROPOSE tests (PLAN.md task D5)."""

import json

import pytest

from seed_data import seed
from src.config import AUTOPILOT_DEFAULT_SCOPE, COST_UNITS_PER_SEND, DAILY_SEND_BUDGET
from src.domain.enums import ActionClass, ActionStatus, ActionType, Mode, OpportunityStatus
from src.engine.permission import (
    classify_action,
    evaluate,
    get_control_status,
    guardrail_checks,
    log_activity,
    set_control_status,
    within_budget,
)
from src.engine.propose import build_decision_card, persist_trace
from src.store.db import connect


@pytest.fixture()
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    seed(conn, reset=True)
    yield conn
    conn.close()


def _ensure_parents(conn):
    """Ensure signal and opportunity rows exist for FK constraints."""
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
    conn.commit()


def _seed_action(conn, action_id="act-1", status="PROPOSED", contact_id="p-acme-ceo",
                 action_type="OUTREACH_EMAIL", cost_units=1):
    """Insert a test action row with required FK parents."""
    _ensure_parents(conn)
    conn.execute(
        "INSERT INTO actions (id, opportunity_id, contact_id, action_type, variant_id, "
        "channel, timing, mode, status, subject, body, cost_units, policy_version) "
        "VALUES (?, 'opp-test', ?, ?, 'v-saas-email-warm-morning', 'EMAIL', 'MORNING', 'PROPOSE', ?, 'Test', 'Hello', ?, 1)",
        (action_id, contact_id, action_type, status, cost_units),
    )
    conn.commit()


def _seed_opportunity(conn, opp_id="opp-test"):
    _ensure_parents(conn)
    conn.commit()


# --- classify_action ---------------------------------------------------------

def test_classify_reversible():
    assert classify_action(ActionType.OUTREACH_EMAIL) == ActionClass.REVERSIBLE


def test_classify_external_for_intro():
    assert classify_action(ActionType.INTRO_REQUEST) == ActionClass.EXTERNAL


def test_classify_high_cost():
    assert classify_action(ActionType.OUTREACH_EMAIL, cost_units=15) == ActionClass.HIGH_COST


def test_classify_linkedin_is_reversible():
    assert classify_action(ActionType.LINKEDIN_CONNECT) == ActionClass.REVERSIBLE


# --- within_budget -----------------------------------------------------------

def test_within_budget_fresh_db(db):
    assert within_budget(db, COST_UNITS_PER_SEND) is True


def test_within_budget_exceeded(db):
    # Ensure parent rows exist
    _ensure_parents(db)
    # Create a separate opportunity for budget test
    db.execute("INSERT INTO opportunities (id, company_id, signal_id, status, score) VALUES ('opp-b', 'c-acme', 'sig-test', 'QUALIFIED', 0.8)")
    # Fill up daily budget
    for i in range(DAILY_SEND_BUDGET):
        db.execute(
            "INSERT INTO actions (id, opportunity_id, contact_id, action_type, variant_id, "
            "channel, timing, mode, status, cost_units, policy_version) "
            "VALUES (?, 'opp-b', 'p-acme-ceo', 'OUTREACH_EMAIL', 'v-x', 'EMAIL', 'MORNING', "
            "'PROPOSE', 'SENT', 1, 1)",
            (f"act-budget-{i}",),
        )
    db.commit()
    assert within_budget(db, COST_UNITS_PER_SEND) is False


# --- guardrail_checks -------------------------------------------------------

def test_guardrails_pass_clean(db):
    blocks = guardrail_checks(db, "OUTREACH_EMAIL", "p-acme-ceo", 1, "Hello there")
    # Should have mandatory_approval for REVERSIBLE but no content blocks
    assert not any("banned_phrase" in b for b in blocks)
    assert not any("pii" in b for b in blocks)


def test_guardrails_catch_banned_phrase(db):
    blocks = guardrail_checks(db, "OUTREACH_EMAIL", "p-acme-ceo", 1, "This is a limited time offer")
    assert any("banned_phrase" in b for b in blocks)


def test_guardrails_catch_pii(db):
    blocks = guardrail_checks(db, "OUTREACH_EMAIL", "p-acme-ceo", 1, "Send me your password")
    assert any("pii" in b for b in blocks)


def test_guardrails_intro_request_mandatory(db):
    blocks = guardrail_checks(db, "INTRO_REQUEST", "p-acme-ceo", 1, "Hello")
    assert any("mandatory_approval" in b for b in blocks)


def test_guardrails_high_cost_mandatory(db):
    blocks = guardrail_checks(db, "OUTREACH_EMAIL", "p-acme-ceo", 15, "Hello")
    assert any("mandatory_approval" in b for b in blocks)


def test_guardrails_rate_limit(db):
    # First action passes
    blocks1 = guardrail_checks(db, "OUTREACH_EMAIL", "p-acme-ceo", 1, "Hello")
    assert not any("rate_limit" in b for b in blocks1)

    # Insert a recent action → rate limit triggers
    _ensure_parents(db)
    db.execute(
        "INSERT INTO actions (id, opportunity_id, contact_id, action_type, variant_id, "
        "channel, timing, mode, status, cost_units, policy_version) "
        "VALUES ('act-rate', 'opp-test', 'p-acme-ceo', 'OUTREACH_EMAIL', 'v-x', 'EMAIL', "
        "'MORNING', 'PROPOSE', 'SENT', 1, 1)",
    )
    db.commit()
    blocks2 = guardrail_checks(db, "OUTREACH_EMAIL", "p-acme-ceo", 1, "Hello again")
    assert any("rate_limit" in b for b in blocks2)


def test_guardrails_follow_up_limit(db):
    _ensure_parents(db)
    # Insert max follow-ups
    for i in range(3):
        db.execute(
            "INSERT INTO actions (id, opportunity_id, contact_id, action_type, variant_id, "
            "channel, timing, mode, status, cost_units, policy_version) "
            "VALUES (?, 'opp-test', 'p-acme-ceo', 'FOLLOW_UP', 'v-x', 'EMAIL', "
            "'MORNING', 'PROPOSE', 'SENT', 1, 1)",
            (f"act-fu-{i}",),
        )
    db.commit()
    blocks = guardrail_checks(db, "FOLLOW_UP", "p-acme-ceo", 1, "Following up")
    assert any("follow_up_limit" in b for b in blocks)


# --- evaluate (mode routing) ------------------------------------------------

def test_propose_mode_always_requires_approval(db):
    decision = evaluate(db, "OUTREACH_EMAIL", "p-acme-ceo", 1, "Hello", mode=Mode.PROPOSE)
    assert decision.requires_approval is True
    assert decision.mode == Mode.PROPOSE


def test_autopilot_within_scope_auto_executes(db):
    scope = {
        "enabled": True,
        "allowed_segments": ["saas-b2b"],
        "allowed_channels": ["EMAIL"],
        "max_sends_per_day": 10,
        "max_cost_units_per_action": 3,
        "allowed_timing": ["MORNING"],
    }
    decision = evaluate(
        db, "OUTREACH_EMAIL", "p-acme-ceo", 1, "Hello",
        mode=Mode.AUTOPILOT, scope=scope,
    )
    assert decision.requires_approval is False


def test_autopilot_outside_scope_requires_approval(db):
    scope = {
        "enabled": True,
        "allowed_segments": ["fintech"],  # acme is saas-b2b
        "allowed_channels": [],
        "max_sends_per_day": 10,
        "max_cost_units_per_action": 3,
        "allowed_timing": [],
    }
    decision = evaluate(
        db, "OUTREACH_EMAIL", "p-acme-ceo", 1, "Hello",
        mode=Mode.AUTOPILOT, scope=scope,
    )
    assert decision.requires_approval is True


def test_autopilot_intro_request_always_requires(db):
    scope = {
        "enabled": True,
        "allowed_segments": [],
        "allowed_channels": [],
        "max_sends_per_day": 10,
        "max_cost_units_per_action": 3,
        "allowed_timing": [],
    }
    decision = evaluate(
        db, "INTRO_REQUEST", "p-acme-ceo", 1, "Hello",
        mode=Mode.AUTOPILOT, scope=scope,
    )
    assert decision.requires_approval is True


def test_autopilot_disabled_requires_approval(db):
    decision = evaluate(
        db, "OUTREACH_EMAIL", "p-acme-ceo", 1, "Hello",
        mode=Mode.AUTOPILOT, scope=AUTOPILOT_DEFAULT_SCOPE,
    )
    assert decision.requires_approval is True


# --- kill switch -------------------------------------------------------------

def test_kill_switch_lifecycle():
    assert get_control_status() == "running"
    set_control_status("paused")
    assert get_control_status() == "paused"
    set_control_status("stopped")
    assert get_control_status() == "stopped"
    set_control_status("running")
    assert get_control_status() == "running"


# --- activity trail ----------------------------------------------------------

def test_log_activity(db):
    _seed_action(db, action_id="act-1")
    log_activity(db, "user", "act-1", "approve", status="APPROVED")
    row = db.execute("SELECT * FROM activity WHERE action_id = 'act-1'").fetchone()
    assert row is not None
    assert row["actor"] == "user"
    assert row["event"] == "approve"
    assert row["status"] == "APPROVED"


def test_log_activity_with_reason(db):
    _seed_action(db, action_id="act-2")
    log_activity(db, "user", "act-2", "reject", status="REJECTED", reason="too_salesy")
    row = db.execute("SELECT * FROM activity WHERE action_id = 'act-2'").fetchone()
    assert row["reason"] == "too_salesy"


def test_log_activity_control_event(db):
    log_activity(db, "user", None, "control", status="paused", detail="Kill switch: pause")
    row = db.execute("SELECT * FROM activity WHERE event = 'control'").fetchone()
    assert row is not None
    assert row["status"] == "paused"


# --- decision card -----------------------------------------------------------

def test_build_decision_card(db):
    _seed_opportunity(db)
    _seed_action(db, action_id="act-card")
    row = db.execute("SELECT * FROM actions WHERE id = 'act-card'").fetchone()
    card = build_decision_card(db, dict(row))
    assert card.action_id == "act-card"
    assert card.action_type == ActionType.OUTREACH_EMAIL
    assert card.channel.value == "EMAIL"
    assert len(card.why) > 0
    assert len(card.guardrails) > 0


def test_persist_trace(db):
    _seed_action(db, action_id="act-trace")
    trace = {"qualification": {"score": 0.85}, "nbam": {"variant": "v-saas-email-warm-morning"}}
    persist_trace(db, "act-trace", trace)
    row = db.execute("SELECT decision_trace FROM actions WHERE id = 'act-trace'").fetchone()
    stored = json.loads(row["decision_trace"])
    assert stored["qualification"]["score"] == 0.85
