"""Tests for revenue attribution / ARR pipeline (Issue #45, P2-6)."""

import pytest

from seed_data import seed
from src.domain.enums import OutcomeResult
from src.domain.models import Outcome
from src.engine.observe import record_outcome
from src.engine.revenue import attribution, mark_won, pipeline
from src.store.db import connect


@pytest.fixture()
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    seed(conn, reset=True)
    yield conn
    conn.close()


def _seed_action(conn, action_id="act-rev", variant_id="v-saas-email-warm-morning",
                 opportunity_id="opp-rev", channel="EMAIL", segment="saas-b2b",
                 action_type="OUTREACH_EMAIL", policy_version=1, status="SENT"):
    conn.execute(
        "INSERT OR IGNORE INTO opportunities (id, company_id, signal_id, status, score, pipeline_stage) "
        "VALUES (?, 'c-acme', 'sig-rev', 'QUALIFIED', 0.8, 'QUALIFIED')",
        (opportunity_id,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO actions (id, opportunity_id, contact_id, action_type, variant_id, "
        "channel, timing, mode, status, subject, body, cost_units, policy_version, segment) "
        "VALUES (?, ?, 'p-acme-ceo', ?, ?, "
        "?, 'MORNING', 'PROPOSE', ?, 'Test', 'Hello', 1, ?, ?)",
        (action_id, opportunity_id, action_type, variant_id, channel, status, policy_version, segment),
    )
    conn.commit()


def _sig(conn):
    if not conn.execute("SELECT 1 FROM signals WHERE id = 'sig-rev'").fetchone():
        conn.execute(
            "INSERT INTO signals (id, company_id, type, payload, detected_at) "
            "VALUES ('sig-rev', 'c-acme', 'FUNDING', '{}', '2026-01-15T10:00:00')"
        )
        conn.commit()


def test_mark_won_sets_arr_from_segment(db):
    conn = db
    _sig(conn)
    _seed_action(conn)
    won = mark_won(conn, "opp-rev")
    assert won["pipeline_stage"] == "WON"
    assert won["arr"] == 12000  # saas-b2b prior
    assert won["won_at"]
    # Idempotent
    won2 = mark_won(conn, "opp-rev")
    assert won2["arr"] == 12000


def test_mark_won_missing_returns_none(db):
    assert mark_won(db, "nope") is None


def test_meeting_outcome_marks_opportunity_won(db):
    conn = db
    _sig(conn)
    _seed_action(conn)
    outcome = Outcome(
        action_id="act-rev",
        result=OutcomeResult.MEETING,
        detail="synthetic",
        at="2026-08-13T10:00:00",
    )
    record_outcome(conn, outcome)
    opp = conn.execute(
        "SELECT pipeline_stage, arr FROM opportunities WHERE id = 'opp-rev'"
    ).fetchone()
    assert opp["pipeline_stage"] == "WON"
    assert opp["arr"] == 12000


def test_no_meeting_no_won(db):
    conn = db
    _sig(conn)
    _seed_action(conn)
    outcome = Outcome(
        action_id="act-rev",
        result=OutcomeResult.NO_RESPONSE,
        detail="synthetic",
        at="2026-08-13T10:00:00",
    )
    record_outcome(conn, outcome)
    opp = conn.execute(
        "SELECT pipeline_stage FROM opportunities WHERE id = 'opp-rev'"
    ).fetchone()
    assert opp["pipeline_stage"] != "WON"


def test_pipeline_funnel_counts_and_arr(db):
    conn = db
    _sig(conn)
    _seed_action(conn)
    mark_won(conn, "opp-rev")
    # Add a qualified-only opp
    conn.execute(
        "INSERT OR IGNORE INTO opportunities (id, company_id, signal_id, status, score, pipeline_stage) "
        "VALUES ('opp-q', 'c-acme', 'sig-rev', 'QUALIFIED', 0.5, 'QUALIFIED')"
    )
    conn.commit()
    funnel = {f["stage"]: f for f in pipeline(conn)}
    assert funnel["WON"]["count"] == 1
    assert funnel["WON"]["arr"] == 12000
    assert funnel["QUALIFIED"]["count"] == 1  # opp-q (opp-rev moved to WON)


def _second_company(conn):
    """A developer-tools segment company for a second deal."""
    conn.execute(
        "INSERT OR IGNORE INTO companies (id, name, segment, stage, employees, tags) "
        "VALUES ('c-devtools', 'DevTools Co', 'developer-tools', 'seed', 20, '[]')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO contacts (id, company_id, name, title, email, warmth) "
        "VALUES ('p-devtools-ceo', 'c-devtools', 'Dev CEO', 'CEO', 'dev@tools.com', 'cold')"
    )
    conn.commit()


def test_attribution_ranks_variants_by_revenue(db):
    conn = db
    _sig(conn)
    _second_company(conn)
    # Two deals on different segments → different ARR
    _seed_action(conn, action_id="a1", variant_id="v-saas-email-warm-morning",
                 opportunity_id="opp1", segment="saas-b2b")
    mark_won(conn, "opp1")
    _seed_action(conn, action_id="a2", variant_id="v-saas-email-cold-afternoon",
                 opportunity_id="opp2", segment="developer-tools", policy_version=2)
    conn.execute(
        "UPDATE opportunities SET company_id = 'c-devtools' WHERE id = 'opp2'"
    )
    conn.commit()
    mark_won(conn, "opp2")

    attr = attribution(conn)
    variants = {v["key"]: v for v in attr["variant"]}
    assert variants["v-saas-email-warm-morning"]["arr"] == 12000
    assert variants["v-saas-email-cold-afternoon"]["arr"] == 18000
    # Sorted desc by ARR
    assert attr["variant"][0]["key"] == "v-saas-email-cold-afternoon"
    # Segment + policy_version dimensions present
    segments = {s["key"]: s for s in attr["segment"]}
    assert segments["saas-b2b"]["arr"] == 12000
    assert segments["developer-tools"]["arr"] == 18000
    versions = {p["key"]: p for p in attr["policy_version"]}
    assert versions["1"]["deals"] == 1
    assert versions["2"]["deals"] == 1


def test_attribution_empty_db(db):
    assert attribution(db) == {"variant": [], "channel": [], "segment": [],
                               "action_type": [], "policy_version": []}
