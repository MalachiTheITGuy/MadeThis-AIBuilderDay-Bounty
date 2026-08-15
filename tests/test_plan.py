"""DECIDE: plan + NBAM tests (PLAN.md task C3)."""

import json
import random

import pytest

from seed_data import seed
from src.domain.enums import ActionType, Channel, TimingSlot, WarmthSignal
from src.domain.models import Experiment, PlannedAction
from src.engine.plan import (
    action_type_for_warmth,
    choose_next_best_action,
    select_variant,
)
from src.store.db import connect


@pytest.fixture()
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    seed(conn, reset=True)
    yield conn
    conn.close()


# --- action_type_for_warmth --------------------------------------------------

def test_warmth_replied_gives_intro():
    assert action_type_for_warmth(WarmthSignal.REPLIED) == ActionType.INTRO_REQUEST


def test_warmth_met_gives_intro():
    assert action_type_for_warmth(WarmthSignal.MET) == ActionType.INTRO_REQUEST


def test_warmth_engaged_gives_outreach():
    assert action_type_for_warmth(WarmthSignal.ENGAGED) == ActionType.OUTREACH_EMAIL


def test_warmth_cold_gives_outreach():
    assert action_type_for_warmth(WarmthSignal.COLD) == ActionType.OUTREACH_EMAIL


def test_warmth_string_input():
    assert action_type_for_warmth("replied") == ActionType.INTRO_REQUEST
    assert action_type_for_warmth("cold") == ActionType.OUTREACH_EMAIL


# --- select_variant (Thompson sampling) -------------------------------------

def test_select_variant_returns_experiment_for_segment(db):
    rng = random.Random(42)
    variant = select_variant(db, "saas-b2b", rng)
    assert isinstance(variant, Experiment)
    assert variant.segment == "saas-b2b"


def test_select_variant_fallback_to_any_segment(db):
    rng = random.Random(42)
    variant = select_variant(db, "nonexistent-segment", rng)
    assert isinstance(variant, Experiment)


def test_select_variant_deterministic_with_seed(db):
    v1 = select_variant(db, "saas-b2b", random.Random(42))
    v2 = select_variant(db, "saas-b2b", random.Random(42))
    assert v1.variant_id == v2.variant_id


def test_select_variant_respects_stats(db):
    """A variant with more replies should be sampled more often (exploitation)."""
    # Give v-saas-email-warm-morning strong stats
    db.execute(
        "UPDATE experiments SET stats = ? WHERE variant_id = 'v-saas-email-warm-morning'",
        (json.dumps({"sent": 20, "replies": 10, "meetings": 3, "positive": 8, "negative": 1, "unsub": 0}),),
    )
    db.commit()

    # Sample 100 times — should favor the strong variant
    counts = {}
    for i in range(100):
        v = select_variant(db, "saas-b2b", random.Random(i))
        counts[v.variant_id] = counts.get(v.variant_id, 0) + 1

    assert counts.get("v-saas-email-warm-morning", 0) > 35


def test_select_variant_exploration_with_uniform_stats(db):
    """With uniform zero stats, all variants should be explored."""
    counts = set()
    for i in range(200):
        v = select_variant(db, "saas-b2b", random.Random(i))
        counts.add(v.variant_id)
    # Should have seen at least 2 different variants
    assert len(counts) >= 2


# --- choose_next_best_action ------------------------------------------------

def test_choose_next_best_action_returns_planned_action(db):
    rng = random.Random(42)
    opp = {"company_id": "c-acme", "signal_id": "sig-1"}
    action = choose_next_best_action(db, opp, rng)
    assert isinstance(action, PlannedAction)
    assert action.channel in (Channel.EMAIL, Channel.LINKEDIN)
    assert action.timing in TimingSlot


def test_choose_next_best_action_uses_warmth(db):
    """c-epsilon has COLD contact with no warm edges → OUTREACH_EMAIL."""
    rng = random.Random(42)
    opp = {"company_id": "c-epsilon", "signal_id": "sig-1"}
    action = choose_next_best_action(db, opp, rng)
    # Hiro Tanaka is COLD, no warm intro → OUTREACH_EMAIL
    assert action.action_type == ActionType.OUTREACH_EMAIL


def test_choose_next_best_action_warm_intro(db):
    """c-betacorp has warm edge to c-gamma-vp (MET) → INTRO_REQUEST via warm graph."""
    rng = random.Random(42)
    opp = {"company_id": "c-gamma", "signal_id": "sig-1"}
    action = choose_next_best_action(db, opp, rng)
    # Frank Miller is MET → INTRO_REQUEST
    assert action.action_type == ActionType.INTRO_REQUEST


def test_choose_next_best_action_expected_effect_contains_variant(db):
    rng = random.Random(42)
    opp = {"company_id": "c-acme", "signal_id": "sig-1"}
    action = choose_next_best_action(db, opp, rng)
    assert "Variant" in action.expected_effect
    assert action.variant_id in action.expected_effect


def test_choose_next_best_action_confidence_range(db):
    rng = random.Random(42)
    opp = {"company_id": "c-acme", "signal_id": "sig-1"}
    action = choose_next_best_action(db, opp, rng)
    assert 0.0 <= action.confidence <= 0.95
