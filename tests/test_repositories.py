"""Tests for the repository layer (Issue #22)."""

import json
import tempfile
from pathlib import Path

from src.store.db import connect
from src.store.repositories import (
    ActionRepository,
    ActivityRepository,
    CompanyRepository,
    ContactRepository,
    OpportunityRepository,
    OutcomeRepository,
    PolicyRepository,
    SignalRepository,
    WarmEdgeRepository,
)


def _setup():
    tmp = tempfile.mktemp(suffix=".db")
    conn = connect(tmp)
    conn.execute(
        "INSERT INTO companies (id, name, segment, stage, employees, tags) "
        "VALUES ('c1', 'Acme', 'saas-b2b', 'seed', 50, '[]')"
    )
    conn.execute(
        "INSERT INTO contacts (id, company_id, name, title, email, warmth) "
        "VALUES ('k1', 'c1', 'Kay', 'VP Sales', 'k@acme.com', 'warm')"
    )
    conn.execute(
        "INSERT INTO contacts (id, company_id, name, title, email, warmth) "
        "VALUES ('k2', 'c1', 'Bob', 'CTO', 'b@acme.com', 'cold')"
    )
    conn.execute(
        "INSERT INTO signals (id, company_id, type, payload, detected_at) "
        "VALUES ('s1', 'c1', 'FUNDING', '{}', '2026-01-01')"
    )
    conn.commit()
    return conn, Path(tmp)


def test_company_repository():
    conn, path = _setup()
    try:
        repo = CompanyRepository(conn)
        assert repo.get("c1")["name"] == "Acme"
        assert repo.get("missing") is None
        assert [c["name"] for c in repo.list_all()] == ["Acme"]
        assert [c["name"] for c in repo.list_by_segment("saas-b2b")] == ["Acme"]
        assert [c["name"] for c in repo.list_by_segment("other")] == []
        assert [c["name"] for c in repo.search("Acme")] == ["Acme"]
        assert [c["name"] for c in repo.search("zzz")] == []
    finally:
        conn.close()
        path.unlink()


def test_contact_repository():
    conn, path = _setup()
    try:
        repo = ContactRepository(conn)
        assert repo.get("k1")["name"] == "Kay"
        assert len(repo.list_by_company("c1")) == 2
        assert [c["name"] for c in repo.list_warm()] == ["Kay"]
    finally:
        conn.close()
        path.unlink()


def test_signal_repository():
    conn, path = _setup()
    try:
        repo = SignalRepository(conn)
        assert repo.get("s1")["type"] == "FUNDING"
        assert repo.exists("c1", "FUNDING", "2025-01-01") is True
        assert repo.exists("c1", "FUNDING", "2026-06-01") is False
    finally:
        conn.close()
        path.unlink()


def test_opportunity_repository():
    conn, path = _setup()
    try:
        repo = OpportunityRepository(conn)
        repo.create("o1", "c1", "s1", 0.8, ["icp"], {"why": "x"})
        assert repo.get("o1")["score"] == 0.8
        assert [o["id"] for o in repo.list_qualified()] == ["o1"]
        repo.update_status("o1", "APPROVED")
        assert [o["id"] for o in repo.list_by_status("APPROVED")] == ["o1"]
        assert [o["id"] for o in repo.list_active()] == ["o1"]
    finally:
        conn.close()
        path.unlink()


def test_action_repository():
    conn, path = _setup()
    try:
        repo = ActionRepository(conn)
        conn.execute(
            "INSERT INTO opportunities (id, company_id, signal_id, status, score) "
            "VALUES ('o1', 'c1', 's1', 'QUALIFIED', 0.8)"
        )
        conn.execute(
            "INSERT INTO actions (id, opportunity_id, contact_id, action_type, variant_id, channel, timing, mode, status, cost_units) "
            "VALUES ('a1', 'o1', 'k1', 'OUTREACH_EMAIL', 'v1', 'EMAIL', '09:30', 'PROPOSE', 'PROPOSED', 1)"
        )
        conn.commit()
        assert [a["id"] for a in repo.list_pending()] == ["a1"]
        repo.update_status("a1", "SENT")
        assert [a["id"] for a in repo.list_by_status("SENT")] == ["a1"]
        assert repo.count_sent_since("2026-01-01") == 1
        assert repo.budget_used("2026-01-01") == 1
    finally:
        conn.close()
        path.unlink()


def test_outcome_repository():
    conn, path = _setup()
    try:
        repo = OutcomeRepository(conn)
        conn.execute(
            "INSERT INTO opportunities (id, company_id, signal_id, status) VALUES ('o1', 'c1', 's1', 'QUALIFIED')"
        )
        conn.execute(
            "INSERT INTO actions (id, opportunity_id, contact_id, action_type, variant_id, channel, timing, mode, status) "
            "VALUES ('a1', 'o1', 'k1', 'OUTREACH_EMAIL', 'v1', 'EMAIL', '09:30', 'PROPOSE', 'SENT')"
        )
        conn.commit()
        repo.record("x1", "a1", "REPLY", "replied", "2026-01-02")
        assert repo.list_by_action("a1")[0]["result"] == "REPLY"
        assert len(repo.list_all()) == 1
    finally:
        conn.close()
        path.unlink()


def test_activity_repository():
    conn, path = _setup()
    try:
        repo = ActivityRepository(conn)
        repo.log("USER", None, "control", status="paused")
        repo.log("AGENT", None, "scan", status="ok")
        all_rows = repo.list()
        assert len(all_rows) == 2
        filtered = repo.list(event="scan")
        assert len(filtered) == 1
        assert filtered[0]["actor"] == "AGENT"
        assert len(repo.list(limit=1)) == 1
        assert len(repo.list(offset=1)) == 1
    finally:
        conn.close()
        path.unlink()


def test_warm_edge_repository():
    conn, path = _setup()
    try:
        repo = WarmEdgeRepository(conn)
        conn.execute(
            "INSERT INTO warm_edges (contact_a, contact_b, strength, direction) "
            "VALUES ('k1', 'k2', 0.9, 'mutual')"
        )
        conn.commit()
        assert len(repo.list_all()) == 1
        assert len(repo.list_for_contact("k1")) == 1
        assert repo.get("k1", "k2")["strength"] == 0.9
        assert repo.get("k2", "k1") is not None  # symmetric lookup
    finally:
        conn.close()
        path.unlink()


def test_policy_repository():
    conn, path = _setup()
    try:
        repo = PolicyRepository(conn)
        assert repo.current() is None
        repo.insert(1, {"brevity_weight": 50}, "test")
        assert repo.current()["version"] == 1
        assert repo.current()["policy"]["brevity_weight"] == 50
        assert len(repo.list_versions()) == 1
    finally:
        conn.close()
        path.unlink()


def test_activity_repository_pagination_and_filter():
    conn, path = _setup()
    try:
        repo = ActivityRepository(conn)
        for i in range(5):
            repo.log("USER", None, "event", status=f"s{i}")
        assert len(repo.list(limit=3)) == 3
        assert len(repo.list(status="s2")) == 1
        assert repo.list(status="s2")[0]["status"] == "s2"
    finally:
        conn.close()
        path.unlink()
