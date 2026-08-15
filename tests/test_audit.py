"""Tests for the trust & audit surface (Issue #42, P2-3)."""

import pytest

from seed_data import seed
from src.domain.enums import OutcomeResult
from src.engine.audit import audit_export, explain_action, pii_report
from src.engine.permission import log_activity
from src.store.db import connect


@pytest.fixture()
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    seed(conn, reset=True)
    yield conn
    conn.close()


def _seed_action(conn, action_id="act-audit", body="Hello there", subject="Intro",
                 variant_id="v-saas-email-warm-morning"):
    if not conn.execute("SELECT 1 FROM signals WHERE id = 'sig-a'").fetchone():
        conn.execute(
            "INSERT INTO signals (id, company_id, type, payload, detected_at) "
            "VALUES ('sig-a', 'c-acme', 'FUNDING', '{}', '2026-01-15T10:00:00')"
        )
    if not conn.execute("SELECT 1 FROM opportunities WHERE id = 'opp-a'").fetchone():
        conn.execute(
            "INSERT INTO opportunities (id, company_id, signal_id, status, score) "
            "VALUES ('opp-a', 'c-acme', 'sig-a', 'QUALIFIED', 0.8)"
        )
    conn.execute(
        "INSERT INTO actions (id, opportunity_id, contact_id, action_type, variant_id, "
        "channel, timing, mode, status, subject, body, cost_units, policy_version, decision_trace) "
        "VALUES (?, 'opp-a', 'p-acme-ceo', 'OUTREACH_EMAIL', ?, "
        "'EMAIL', 'MORNING', 'PROPOSE', 'PROPOSED', ?, ?, 1, 1, "
        "'{\"why\": \"icp fit\", \"evidence\": [\"funding round\"]}')",
        (action_id, variant_id, subject, body),
    )
    conn.commit()


def test_audit_export_reconstructs_session(db):
    _seed_action(db)
    conn = db
    conn.execute(
        "INSERT INTO outcomes (id, action_id, result, detail, at) "
        "VALUES ('out-audit', 'act-audit', 'MEETING', 'warm', '2026-08-13T10:00:00')"
    )
    log_activity(conn, "USER", "act-audit", "approve", status="APPROVED",
                 reason="looks good")
    conn.commit()

    export = audit_export(conn)
    assert len(export["actions"]) >= 1
    action = next(a for a in export["actions"] if a["id"] == "act-audit")
    assert action["decision_trace"]["why"] == "icp fit"
    assert action["decision_trace"]["evidence"] == ["funding round"]
    assert action["company"]  # joined company name
    assert action["contact"]  # joined contact name

    assert any(o["result"] == "MEETING" for o in export["outcomes"])
    assert any(a["event"] == "approve" and a["reason"] == "looks good" for a in export["activity"])
    assert len(export["policies"]) >= 1
    # All five top-level sections present
    for section in ("actions", "outcomes", "activity", "policies", "schema"):
        assert section in export


def test_audit_export_serializes_guardrails_and_json(db):
    _seed_action(db, body="boring body")
    conn = db
    conn.execute(
        "UPDATE actions SET guardrail_blocks = '[\"cost too high\"]' WHERE id = 'act-audit'"
    )
    conn.commit()
    export = audit_export(conn)
    action = next(a for a in export["actions"] if a["id"] == "act-audit")
    assert action["guardrail_blocks"] == ["cost too high"]


def test_explain_action_returns_full_trace(db):
    _seed_action(db)
    trace = explain_action(db, "act-audit")
    assert trace is not None
    assert trace["action_id"] == "act-audit"
    assert trace["decision_trace"]["why"] == "icp fit"
    assert trace["template"]  # from experiments join
    assert trace["variant"]["variant_id"] == "v-saas-email-warm-morning"
    assert trace["policy_snapshot"]["version"] == 1
    assert isinstance(trace["policy_snapshot"]["policy"], dict)


def test_explain_action_missing_returns_none(db):
    assert explain_action(db, "nope") is None


def test_pii_report_finds_violations_with_ids(db):
    _seed_action(db, action_id="bad1", body="send us your social security number")
    _seed_action(db, action_id="bad2", body="guaranteed roi, act now")
    _seed_action(db, action_id="good1", body="hello from Acme")
    report = pii_report(db)
    assert report["checked_actions"] >= 3
    by_id = {v["action_id"]: v for v in report["violations"]}
    assert "bad1" in by_id
    assert any("social security" in v for v in by_id["bad1"]["violations"])
    assert "bad2" in by_id
    assert any("guaranteed roi" in v for v in by_id["bad2"]["violations"])
    assert "good1" not in by_id


def test_pii_report_clean_actions_no_violations(db):
    _seed_action(db, body="just a friendly note")
    report = pii_report(db)
    assert report["checked_actions"] >= 1
    assert report["violations"] == []
