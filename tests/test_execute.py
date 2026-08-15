"""ACT + OBSERVE tests (PLAN.md task D6)."""

import pytest

from seed_data import seed
from src.domain.enums import ActionStatus, OutcomeResult
from src.domain.models import Outcome
from src.engine.execute import (
    ADAPTERS,
    EmailSim,
    LinkedinSim,
    _require_simulation,
    execute_action,
)
from src.engine.observe import (
    poll_synthetic_outcomes,
    record_outcome,
    synthesize_outcome,
)
from src.store.db import connect


@pytest.fixture()
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    seed(conn, reset=True)
    yield conn
    conn.close()


def _seed_action(conn, action_id="act-exec-1", status="APPROVED", channel="EMAIL"):
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
        "VALUES (?, 'opp-test', 'p-acme-ceo', 'OUTREACH_EMAIL', 'v-saas-email-warm-morning', "
        "?, 'MORNING', 'PROPOSE', ?, 'Test', 'Hello', 1, 1)",
        (action_id, channel, status),
    )
    conn.commit()


# --- execute.py: safety guard ------------------------------------------------

def test_simulation_guard_passes():
    """No error when SIMULATION_MODE is on (default in test env)."""
    _require_simulation()


# --- execute.py: EmailSim ----------------------------------------------------

def test_email_sim_sends(db):
    _seed_action(db, action_id="act-email-1")
    status = EmailSim.send(db, "act-email-1")
    assert status == ActionStatus.SENT
    row = db.execute("SELECT status FROM actions WHERE id = 'act-email-1'").fetchone()
    assert row["status"] == "SENT"


def test_email_sim_does_not_make_network_calls():
    """EmailSim has no network imports — verify it's purely local."""
    import inspect
    src = inspect.getsource(EmailSim.send)
    assert "requests" not in src
    assert "urllib" not in src
    assert "httpx" not in src
    assert "aiohttp" not in src


# --- execute.py: LinkedinSim -------------------------------------------------

def test_linkedin_sim_sends(db):
    _seed_action(db, action_id="act-li-1", channel="LINKEDIN")
    status = LinkedinSim.send(db, "act-li-1")
    assert status == ActionStatus.SENT
    row = db.execute("SELECT status FROM actions WHERE id = 'act-li-1'").fetchone()
    assert row["status"] == "SENT"


def test_linkedin_sim_does_not_make_network_calls():
    """LinkedinSim has no network imports — verify it's purely local."""
    import inspect
    src = inspect.getsource(LinkedinSim.send)
    assert "requests" not in src
    assert "urllib" not in src
    assert "httpx" not in src
    assert "aiohttp" not in src


# --- execute.py: execute_action dispatch -------------------------------------

def test_execute_action_dispatches_email(db):
    _seed_action(db, action_id="act-disp-1", channel="EMAIL")
    status = execute_action(db, "act-disp-1", "EMAIL")
    assert status == ActionStatus.SENT


def test_execute_action_dispatches_linkedin(db):
    _seed_action(db, action_id="act-disp-2", channel="LINKEDIN")
    status = execute_action(db, "act-disp-2", "LINKEDIN")
    assert status == ActionStatus.SENT


def test_execute_action_unknown_channel(db):
    _seed_action(db, action_id="act-disp-3")
    with pytest.raises(ValueError, match="No adapter for channel"):
        execute_action(db, "act-disp-3", "SMS")


# --- execute.py: adapters registry -------------------------------------------

def test_all_adapters_are_simulation_only():
    """Every registered adapter must be a simulation class."""
    for name, adapter in ADAPTERS.items():
        assert adapter.__name__.endswith("Sim"), f"Adapter {name} is not a Sim class"


# --- observe.py: record_outcome ----------------------------------------------

def test_record_outcome_inserts_row(db):
    _seed_action(db, action_id="act-out-1")
    outcome = Outcome(
        action_id="act-out-1",
        result=OutcomeResult.REPLY,
        detail="test reply",
    )
    record_outcome(db, outcome)
    row = db.execute("SELECT * FROM outcomes WHERE action_id = 'act-out-1'").fetchone()
    assert row is not None
    assert row["result"] == "REPLY"
    assert row["detail"] == "test reply"


def test_record_outcome_updates_action_status(db):
    _seed_action(db, action_id="act-out-2", status="APPROVED")
    outcome = Outcome(
        action_id="act-out-2",
        result=OutcomeResult.MEETING,
        detail="booked meeting",
    )
    record_outcome(db, outcome)
    row = db.execute("SELECT status FROM actions WHERE id = 'act-out-2'").fetchone()
    assert row["status"] == "SENT"


def test_record_outcome_unknown_action_raises(db):
    outcome = Outcome(
        action_id="nonexistent",
        result=OutcomeResult.NEUTRAL,
    )
    with pytest.raises(ValueError, match="Action not found"):
        record_outcome(db, outcome)


# --- observe.py: synthesize_outcome ------------------------------------------

def test_synthesize_outcome_email_warm(db):
    _seed_action(db, action_id="act-synth-1", channel="EMAIL")
    outcome = synthesize_outcome(db, "act-synth-1", warmth="warm")
    assert outcome.result == OutcomeResult.MEETING
    assert outcome.action_id == "act-synth-1"
    # Verify it was persisted
    row = db.execute("SELECT * FROM outcomes WHERE action_id = 'act-synth-1'").fetchone()
    assert row is not None
    assert row["result"] == "MEETING"


def test_synthesize_outcome_email_cold(db):
    _seed_action(db, action_id="act-synth-2", channel="EMAIL")
    outcome = synthesize_outcome(db, "act-synth-2", warmth="cold")
    assert outcome.result == OutcomeResult.NO_RESPONSE


def test_synthesize_outcome_linkedin_default(db):
    _seed_action(db, action_id="act-synth-3", channel="LINKEDIN")
    # Override action type to LINKEDIN_CONNECT for this test
    db.execute("UPDATE actions SET action_type = 'LINKEDIN_CONNECT' WHERE id = 'act-synth-3'")
    db.commit()
    outcome = synthesize_outcome(db, "act-synth-3")
    assert outcome.result == OutcomeResult.POSITIVE


def test_synthesize_outcome_unknown_action_raises(db):
    with pytest.raises(ValueError, match="Action not found"):
        synthesize_outcome(db, "nonexistent")


# --- observe.py: poll_synthetic_outcomes -------------------------------------

def test_poll_returns_recorded_outcomes(db):
    _seed_action(db, action_id="act-poll-1")
    synthesize_outcome(db, "act-poll-1", warmth="warm")
    outcomes = poll_synthetic_outcomes(db)
    ids = [o.action_id for o in outcomes]
    assert "act-poll-1" in ids


def test_poll_returns_empty_when_no_outcomes(tmp_path):
    conn = connect(tmp_path / "empty.db")
    seed(conn, reset=True)
    outcomes = poll_synthetic_outcomes(conn)
    assert outcomes == []
    conn.close()
