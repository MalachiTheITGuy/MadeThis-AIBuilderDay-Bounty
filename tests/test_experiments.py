"""Tests for the experiment science surface (Issue #41, P2-2)."""

import random

import pytest

from seed_data import seed
from src.domain.enums import OutcomeResult
from src.domain.models import Outcome
from src.engine.experiments import (
    analysis,
    beta_quantile,
    posterior_stats,
    regret_by_cycle,
    win_probability,
)
from src.engine.learn import apply_outcome
from src.store.db import connect


@pytest.fixture()
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    seed(conn, reset=True)
    yield conn
    conn.close()


def _seed_outcome(conn, action_id, variant_id, result, contact_id="p-acme-ceo", at="2026-01-15T10:00:00"):
    """Insert an action + outcome pair with required FK parents."""
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
        "VALUES (?, 'opp-e2e', ?, 'OUTREACH_EMAIL', ?, "
        "'EMAIL', 'MORNING', 'AUTOPILOT', 'SENT', 'Test', 'Hello', 1, 1)",
        (action_id, contact_id, variant_id),
    )
    conn.execute(
        "INSERT INTO outcomes (id, action_id, result, detail, at) "
        "VALUES (?, ?, ?, '', ?)",
        (f"out-{action_id}", action_id, result.value, at),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Beta posterior math
# ---------------------------------------------------------------------------

def test_posterior_stats_mean():
    s = posterior_stats(successes=4, sent=10)
    assert s["posterior_mean"] == round((4 + 1) / (10 + 2), 4)
    assert s["ci_low"] <= s["posterior_mean"] <= s["ci_high"]


def test_posterior_stats_no_data():
    s = posterior_stats(successes=0, sent=0)
    assert s["posterior_mean"] == 0.5  # Beta(1,1) prior mean


def test_beta_quantile_matches_known_values():
    # Beta(2,2) median = 0.5
    assert abs(beta_quantile(0.5, 2, 2) - 0.5) < 0.01
    # Beta(1,1) uniform: 95% CI spans ~0.025..0.975
    assert abs(beta_quantile(0.025, 1, 1) - 0.025) < 0.01
    assert abs(beta_quantile(0.975, 1, 1) - 0.975) < 0.01


def test_win_probability_clear_winner():
    # A(20, 5) should almost always beat B(2, 20)
    p = win_probability(21, 6, [3], [21], n=2000)
    assert p > 0.95


def test_win_probability_no_opponents():
    assert win_probability(5, 5, [], []) == 1.0


# ---------------------------------------------------------------------------
# Analysis surface
# ---------------------------------------------------------------------------

def test_analysis_reports_variants_with_ci(db):
    _seed_outcome(db, "a1", "v-saas-email-warm-morning", OutcomeResult.MEETING)
    _seed_outcome(db, "a2", "v-saas-email-warm-morning", OutcomeResult.MEETING, at="2026-01-15T10:01:00")
    _seed_outcome(db, "a3", "v-saas-email-cold-afternoon", OutcomeResult.NO_RESPONSE, at="2026-01-15T10:02:00")
    result = analysis(db, min_samples=5)
    assert len(result) == 2
    by_id = {r["variant_id"]: r for r in result}
    assert by_id["v-saas-email-warm-morning"]["successes"] == 2
    assert by_id["v-saas-email-warm-morning"]["ci_low"] <= by_id["v-saas-email-warm-morning"]["posterior_mean"] <= by_id["v-saas-email-warm-morning"]["ci_high"]
    assert by_id["v-saas-email-cold-afternoon"]["sent"] == 1
    # Low sample → paused
    assert by_id["v-saas-email-cold-afternoon"]["paused"] is True
    # High sample but still under min → paused; the winner has 2 < 5 too
    assert by_id["v-saas-email-warm-morning"]["paused"] is True


def test_analysis_no_data(db):
    assert analysis(db, min_samples=5) == []


def test_analysis_sorts_by_posterior_mean_desc(db):
    _seed_outcome(db, "a1", "v-saas-email-warm-morning", OutcomeResult.MEETING)
    _seed_outcome(db, "a2", "v-saas-email-cold-afternoon", OutcomeResult.NO_RESPONSE)
    result = analysis(db, min_samples=0)
    means = [r["posterior_mean"] for r in result]
    assert means == sorted(means, reverse=True)


# ---------------------------------------------------------------------------
# Regret / convergence surface
# ---------------------------------------------------------------------------

def test_regret_by_cycle_buckets_history(db):
    # 6 outcomes with cycle_size=3 → 2 cycles
    variants = [
        ("a1", "v-saas-email-warm-morning", OutcomeResult.MEETING),
        ("a2", "v-saas-email-warm-morning", OutcomeResult.MEETING),
        ("a3", "v-saas-email-cold-afternoon", OutcomeResult.NO_RESPONSE),
        ("a4", "v-saas-email-warm-morning", OutcomeResult.MEETING),
        ("a5", "v-saas-email-warm-morning", OutcomeResult.REPLY),
        ("a6", "v-saas-email-cold-afternoon", OutcomeResult.NO_RESPONSE),
    ]
    for i, (aid, vid, res) in enumerate(variants):
        _seed_outcome(db, aid, vid, res, at=f"2026-01-15T10:0{i}:00")
    cycles = regret_by_cycle(db, cycle_size=3)
    assert len(cycles) == 2
    assert cycles[0]["sent"] == 3
    assert cycles[1]["sent"] == 3
    assert all("regret" in c and "achieved_rate" in c and "best_rate" in c for c in cycles)


def test_regret_converges_with_learning(db):
    """As the loop learns (more of the good variant), regret declines."""
    # Simulate learning: early cycles mostly send the cold variant (poor),
    # later cycles mostly the warm variant (good).
    rng = random.Random(7)
    for cycle in range(4):
        at = f"2026-01-1{cycle}0T10:00:00"
        for i in range(5):
            aid = f"c{cycle}-{i}"
            # In later cycles, weight toward the good variant
            good_warm = 0.2 + 0.25 * cycle
            if rng.random() < good_warm:
                vid, res = "v-saas-email-warm-morning", OutcomeResult.MEETING
            else:
                vid, res = "v-saas-email-cold-afternoon", OutcomeResult.NO_RESPONSE
            _seed_outcome(db, aid, vid, res, at=at)

    cycles = regret_by_cycle(db, cycle_size=5)
    assert len(cycles) == 4
    first_regret = cycles[0]["regret"]
    last_regret = cycles[-1]["regret"]
    # Later cycles achieve closer to the best rate → lower regret
    assert last_regret <= first_regret + 0.01
