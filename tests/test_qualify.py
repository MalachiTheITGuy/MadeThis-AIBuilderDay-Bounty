"""SENSE + qualify tests (PLAN.md task B3)."""

from datetime import datetime, timedelta

import pytest

from seed_data import seed
from src.config import QUALIFY_THRESHOLD
from src.domain.enums import OpportunityStatus, SignalType
from src.domain.models import Signal
from src.engine.sense import (
    create_opportunity,
    generate_signals,
    ingest_signal,
    qualify,
)
from src.store.db import connect


@pytest.fixture()
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    seed(conn, reset=True)
    yield conn
    conn.close()


def _make_signal(company_id: str, sig_type: SignalType = SignalType.FUNDING, **overrides) -> Signal:
    defaults = dict(
        id=f"sig-test-{company_id}",
        company_id=company_id,
        type=sig_type,
        payload={"source": "test"},
        detected_at=datetime(2026, 1, 15, 10, 0, 0),
    )
    defaults.update(overrides)
    return Signal(**defaults)


# --- Ingestion + deduplication -----------------------------------------------

def test_ingest_signal_persists(db):
    sig = _make_signal("c-acme")
    assert ingest_signal(db, sig) is True
    row = db.execute("SELECT * FROM signals WHERE id = ?", (sig.id,)).fetchone()
    assert row is not None
    assert row["type"] == "FUNDING"


def test_ingest_deduplicates_within_window(db):
    sig = _make_signal("c-acme")
    assert ingest_signal(db, sig) is True
    # Same company + type within window → duplicate
    sig2 = _make_signal("c-acme", id="sig-dup")
    assert ingest_signal(db, sig2) is False
    count = db.execute("SELECT COUNT(*) AS n FROM signals WHERE company_id = 'c-acme'").fetchone()["n"]
    assert count == 1


def test_ingest_allows_different_type_same_company(db):
    sig1 = _make_signal("c-acme", sig_type=SignalType.FUNDING)
    sig2 = _make_signal("c-acme", sig_type=SignalType.HIRING, id="sig-hire")
    assert ingest_signal(db, sig1) is True
    assert ingest_signal(db, sig2) is True
    count = db.execute("SELECT COUNT(*) AS n FROM signals WHERE company_id = 'c-acme'").fetchone()["n"]
    assert count == 2


def test_ingest_allows_same_type_outside_window(db):
    sig = _make_signal("c-acme", detected_at=datetime(2026, 1, 1, 0, 0, 0))
    assert ingest_signal(db, sig) is True
    # Same company + type but outside 24h window
    sig2 = _make_signal("c-acme", id="sig-outside", detected_at=datetime(2026, 1, 3, 0, 0, 0))
    assert ingest_signal(db, sig2) is True


# --- Qualification scoring ---------------------------------------------------

def test_qualify_returns_none_for_unknown_company(db):
    sig = _make_signal("c-nonexistent")
    assert qualify(db, sig) is None


def test_qualify_funding_signal_high_score(db):
    sig = _make_signal("c-acme", sig_type=SignalType.FUNDING)
    qual = qualify(db, sig)
    assert qual is not None
    # FUNDING on a series-a saas-b2b company should score well
    assert qual.score >= 0.6


def test_qualify_content_signal_lower_score(db):
    sig_funding = _make_signal("c-acme", sig_type=SignalType.FUNDING)
    sig_content = _make_signal("c-acme", sig_type=SignalType.CONTENT, id="sig-content")
    q1 = qualify(db, sig_funding)
    q2 = qualify(db, sig_content)
    assert q1 is not None and q2 is not None
    assert q1.score > q2.score


def test_qualify_captures_fit_notes(db):
    sig = _make_signal("c-acme", sig_type=SignalType.FUNDING)
    qual = qualify(db, sig)
    assert qual is not None
    assert len(qual.fit_notes) >= 3  # signal type, segment, stage, employees
    assert any("FUNDING" in note for note in qual.fit_notes)


def test_qualify_captures_icp_hits_for_target_segment(db):
    sig = _make_signal("c-acme", sig_type=SignalType.FUNDING)
    qual = qualify(db, sig)
    assert qual is not None
    assert any("saas-b2b" in hit for hit in qual.icp_hits)


def test_qualify_non_target_segment_no_segment_icp_hit(db):
    # c-zeta is ecommerce — not in TARGET_SEGMENTS
    sig = _make_signal("c-zeta", sig_type=SignalType.FUNDING)
    qual = qualify(db, sig)
    assert qual is not None
    assert not any("Target segment" in hit for hit in qual.icp_hits)


def test_qualify_tags_bonus(db):
    # c-acme has tags ["data", "seed-funded"] — "seed-funded" is interesting
    sig = _make_signal("c-acme", sig_type=SignalType.FUNDING)
    qual = qualify(db, sig)
    assert qual is not None
    assert any("seed-funded" in hit for hit in qual.icp_hits)


def test_qualify_score_clamped_to_one(db):
    # Even with all bonuses, score should not exceed 1.0
    sig = _make_signal("c-acme", sig_type=SignalType.FUNDING)
    qual = qualify(db, sig)
    assert qual is not None
    assert qual.score <= 1.0
    assert qual.score >= 0.0


# --- Threshold behavior ------------------------------------------------------

def test_qualify_above_threshold_can_create_opportunity(db):
    sig = _make_signal("c-acme", sig_type=SignalType.FUNDING)
    assert ingest_signal(db, sig) is True
    qual = qualify(db, sig)
    assert qual is not None
    if qual.score >= QUALIFY_THRESHOLD:
        opp = create_opportunity(db, sig, qual)
        assert opp.status == OpportunityStatus.QUALIFIED
        assert opp.score == qual.score
        row = db.execute("SELECT * FROM opportunities WHERE id = ?", (opp.id,)).fetchone()
        assert row is not None


def test_qualify_decision_trace_stored(db):
    sig = _make_signal("c-acme", sig_type=SignalType.FUNDING)
    ingest_signal(db, sig)
    qual = qualify(db, sig)
    assert qual is not None
    opp = create_opportunity(db, sig, qual)
    row = db.execute("SELECT decision_trace FROM opportunities WHERE id = ?", (opp.id,)).fetchone()
    import json
    trace = json.loads(row["decision_trace"])
    assert "qualification" in trace
    assert "score" in trace["qualification"]


# --- Signal generation -------------------------------------------------------

def test_generate_signals_returns_list(db):
    signals = generate_signals(db, rng=__import__("random").Random(42))
    assert isinstance(signals, list)
    assert len(signals) > 0


def test_generate_signals_have_valid_company_ids(db):
    signals = generate_signals(db, rng=__import__("random").Random(42))
    company_ids = {r["id"] for r in db.execute("SELECT id FROM companies").fetchall()}
    for sig in signals:
        assert sig.company_id in company_ids


def test_generate_signals_deterministic_with_seed(db):
    import random
    s1 = generate_signals(db, rng=random.Random(42))
    # Re-seed companies
    seed(db, reset=True)
    s2 = generate_signals(db, rng=random.Random(42))
    assert len(s1) == len(s2)
    for a, b in zip(s1, s2):
        assert a.company_id == b.company_id
        assert a.type == b.type
