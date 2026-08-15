"""Tests for the Loop Digest briefing (Issue #40, P2-1)."""

import pytest

from seed_data import seed
from src.domain.enums import OutcomeResult
from src.engine.briefing import _leaderboard_shifts, briefing
from src.engine.permission import log_activity
from src.store.db import connect


@pytest.fixture()
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    seed(conn, reset=True)
    yield conn
    conn.close()


def _ensure_parents(conn):
    if not conn.execute("SELECT 1 FROM signals WHERE id = 'sig-b'").fetchone():
        conn.execute(
            "INSERT INTO signals (id, company_id, type, payload, detected_at) "
            "VALUES ('sig-b', 'c-acme', 'FUNDING', '{}', '2026-01-15T10:00:00')"
        )
    if not conn.execute("SELECT 1 FROM opportunities WHERE id = 'opp-b'").fetchone():
        conn.execute(
            "INSERT INTO opportunities (id, company_id, signal_id, status, score) "
            "VALUES ('opp-b', 'c-acme', 'sig-b', 'QUALIFIED', 0.8)"
        )
    conn.commit()


def _seed_outcome(conn, action_id, variant_id, result, at=None):
    """Insert an action + outcome pair with required FK parents."""
    _ensure_parents(conn)
    conn.execute(
        "INSERT INTO actions (id, opportunity_id, contact_id, action_type, variant_id, "
        "channel, timing, mode, status, subject, body, cost_units, policy_version, created_at) "
        "VALUES (?, 'opp-b', 'p-acme-ceo', 'OUTREACH_EMAIL', ?, "
        "'EMAIL', 'MORNING', 'AUTOPILOT', 'SENT', 'Test', 'Hello', 1, 1, '2026-08-13T10:00:00')",
        (action_id, variant_id),
    )
    conn.execute(
        "INSERT INTO outcomes (id, action_id, result, detail, at) "
        "VALUES (?, ?, ?, '', ?)",
        (f"out-{action_id}", action_id, result.value, at or "2026-08-13T10:00:00"),
    )
    conn.commit()


def test_briefing_returns_structured_sections(db):
    result = briefing(db, period="week")
    for section in ("what_ran", "leaderboard_shifts", "policy_changes",
                    "warm_movements", "needs_attention", "suggested_actions"):
        assert section in result
    assert result["period"] == "week"
    assert result["generated_at"]
    assert isinstance(result["needs_attention"]["pending_approval"], int)
    assert isinstance(result["what_ran"]["total_actions"], int)
    assert isinstance(result["suggested_actions"], list)


def test_briefing_from_real_stored_data(db):
    _seed_outcome(db, "a1", "v-saas-email-warm-morning", OutcomeResult.MEETING)
    _seed_outcome(db, "a2", "v-saas-email-cold-afternoon", OutcomeResult.NO_RESPONSE)
    _seed_outcome(db, "a3", "v-saas-email-warm-morning", OutcomeResult.REPLY)
    result = briefing(db, period="week")
    shifts = {s["variant_id"]: s for s in result["leaderboard_shifts"]}
    assert shifts["v-saas-email-warm-morning"]["sent"] == 2
    assert shifts["v-saas-email-warm-morning"]["success_rate"] == 1.0
    assert shifts["v-saas-email-cold-afternoon"]["sent"] == 1
    assert shifts["v-saas-email-cold-afternoon"]["success_rate"] == 0.0
    assert result["what_ran"]["total_actions"] >= 3


def test_briefing_suggests_pausing_worst_variant(db):
    # Cold variant: 10 sends, 0 success → underperforming suggestion
    for i in range(10):
        _seed_outcome(db, f"cold{i}", "v-saas-email-cold-afternoon",
                      OutcomeResult.NO_RESPONSE)
    _seed_outcome(db, "warm1", "v-saas-email-warm-morning", OutcomeResult.MEETING)
    result = briefing(db, period="week")
    assert any("underperforming" in s for s in result["suggested_actions"])


def test_briefing_highlights_policy_change_source(db):
    # Seed a policy change with a human-decision source
    conn = db
    from src.engine.learn import _get_current_policy, _apply_policy_deltas
    from src.domain.models import PolicyDelta
    if _get_current_policy(conn) is not None:
        _apply_policy_deltas(conn, [PolicyDelta(field="brevity", delta=0.1, source="rejection:too_long")])
    result = briefing(db, period="week")
    sources = [p["source"] for p in result["policy_changes"]]
    assert any("rejection:too_long" in s for s in sources)


def test_briefing_attention_counts(db):
    conn = db
    _ensure_parents(conn)
    conn.execute(
        "INSERT INTO actions (id, opportunity_id, contact_id, action_type, variant_id, "
        "channel, timing, mode, status, subject, body, cost_units, policy_version, created_at) "
        "VALUES ('pending1', 'opp-b', 'p-acme-ceo', 'OUTREACH_EMAIL', 'v-saas-email-warm-morning', "
        "'EMAIL', 'MORNING', 'PROPOSE', 'PROPOSED', 'Test', 'Hello', 1, 1, '2026-08-13T10:00:00')"
    )
    conn.commit()
    result = briefing(db, period="week")
    assert result["needs_attention"]["pending_approval"] >= 1


def test_leaderboard_shifts_ignores_old_outcomes(db):
    _seed_outcome(db, "old1", "v-saas-email-cold-afternoon", OutcomeResult.NO_RESPONSE,
                  at="2020-01-01T00:00:00")
    _seed_outcome(db, "new1", "v-saas-email-warm-morning", OutcomeResult.MEETING)
    shifts = _leaderboard_shifts(db, "2026-01-01T00:00:00")
    by_id = {s["variant_id"]: s for s in shifts}
    assert "v-saas-email-warm-morning" in by_id
    assert "v-saas-email-cold-afternoon" not in by_id
