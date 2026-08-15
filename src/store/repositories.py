"""Repository layer: reusable data access for the gtm-loop pipeline (PLAN.md §3.4).

Centralizes SQL so engine modules don't scatter raw queries. Each repository
wraps a connection and exposes focused lookups/writes used by the engine and
API layers. Connections remain owned by callers (see db.get_connection()).

Repositories:
    CompanyRepository    — find, list by segment/stage/tags
    ContactRepository    — find by company, warmth lookups
    SignalRepository     — dedupe + persist
    OpportunityRepository — find by status/score, create
    ActionRepository     — find by status, queue, budget queries
    OutcomeRepository    — record, query by action
    ActivityRepository   — append-only audit trail
    WarmEdgeRepository   — relationship graph lookups/updates
    PolicyRepository     — current policy, version history
"""

from __future__ import annotations

import json
import sqlite3

from ..domain.enums import OpportunityStatus


class CompanyRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, company_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM companies WHERE id = ?", (company_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_all(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM companies ORDER BY name")]

    def list_by_segment(self, segment: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM companies WHERE segment = ?", (segment,)
        )]

    def search(self, query: str) -> list[dict]:
        like = f"%{query}%"
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM companies WHERE name LIKE ? OR segment LIKE ?",
            (like, like),
        )]


class ContactRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, contact_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_by_company(self, company_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM contacts WHERE company_id = ?", (company_id,)
        )]

    def list_warm(self) -> list[dict]:
        """Contacts with warmth above 'cold' (potential warm-path outreach)."""
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM contacts WHERE warmth != 'cold' ORDER BY warmth"
        )]


class SignalRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, signal_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM signals WHERE id = ?", (signal_id,)
        ).fetchone()
        return dict(row) if row else None

    def exists(self, company_id: str, signal_type: str, since: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM signals WHERE company_id = ? AND type = ? AND detected_at >= ? LIMIT 1",
            (company_id, signal_type, since),
        ).fetchone()
        return row is not None


class OpportunityRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, opportunity_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM opportunities WHERE id = ?", (opportunity_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_by_status(self, *statuses: str) -> list[dict]:
        if not statuses:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM opportunities ORDER BY created_at DESC"
            )]
        marks = ",".join("?" for _ in statuses)
        return [dict(r) for r in self.conn.execute(
            f"SELECT * FROM opportunities WHERE status IN ({marks}) ORDER BY created_at DESC",
            statuses,
        )]

    def list_qualified(self) -> list[dict]:
        return self.list_by_status(OpportunityStatus.QUALIFIED.value)

    def list_active(self) -> list[dict]:
        """Opportunities not dismissed or skipped."""
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM opportunities WHERE status NOT IN ('DISMISSED', 'SKIPPED')"
        )]

    def create(self, opportunity_id: str, company_id: str, signal_id: str,
               score: float, fit_notes: list[str] | None = None,
               decision_trace: dict | None = None) -> None:
        self.conn.execute(
            "INSERT INTO opportunities (id, company_id, signal_id, status, score, fit_notes, decision_trace) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                opportunity_id, company_id, signal_id,
                OpportunityStatus.QUALIFIED.value, score,
                json.dumps(fit_notes or []),
                json.dumps(decision_trace or {}),
            ),
        )

    def update_status(self, opportunity_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE opportunities SET status = ? WHERE id = ?",
            (status, opportunity_id),
        )


class ActionRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, action_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
        return dict(row) if row else None

    def list_by_status(self, *statuses: str) -> list[dict]:
        if not statuses:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM actions ORDER BY created_at DESC"
            )]
        marks = ",".join("?" for _ in statuses)
        return [dict(r) for r in self.conn.execute(
            f"SELECT * FROM actions WHERE status IN ({marks}) ORDER BY created_at DESC",
            statuses,
        )]

    def list_pending(self) -> list[dict]:
        """Actions awaiting approval (status = PROPOSED)."""
        return self.list_by_status("PROPOSED")

    def update_status(self, action_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE actions SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, action_id),
        )

    def count_sent_since(self, since: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM actions WHERE status = 'SENT' AND created_at >= ?",
            (since,),
        ).fetchone()
        return row["n"]

    def budget_used(self, since: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(cost_units), 0) AS total FROM actions "
            "WHERE created_at >= ? AND status != 'BLOCKED'",
            (since,),
        ).fetchone()
        return row["total"]


class OutcomeRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def record(self, outcome_id: str, action_id: str, result: str,
               detail: str, at: str) -> None:
        self.conn.execute(
            "INSERT INTO outcomes (id, action_id, result, detail, at) VALUES (?, ?, ?, ?, ?)",
            (outcome_id, action_id, result, detail, at),
        )

    def list_by_action(self, action_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM outcomes WHERE action_id = ? ORDER BY at DESC",
            (action_id,),
        )]

    def list_all(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM outcomes ORDER BY at DESC"
        )]


class ActivityRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def log(self, actor: str, action_id: str | None, event: str, status: str = "",
            outcome: str = "", reason: str = "", policy_version: int = 0,
            detail: str = "") -> None:
        self.conn.execute(
            "INSERT INTO activity (actor, action_id, event, status, outcome, reason, policy_version, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (actor, action_id, event, status, outcome, reason, policy_version, detail),
        )
        self.conn.commit()

    def list(self, limit: int = 50, offset: int = 0,
             actor: str = "", status: str = "", event: str = "") -> list[dict]:
        conditions = []
        params: list = []
        if actor:
            conditions.append("actor = ?")
            params.append(actor)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if event:
            conditions.append("event = ?")
            params.append(event)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self.conn.execute(
            f"SELECT * FROM activity {where} ORDER BY at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


class WarmEdgeRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, contact_a: str, contact_b: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM warm_edges WHERE (contact_a = ? AND contact_b = ?) "
            "OR (contact_a = ? AND contact_b = ?)",
            (contact_a, contact_b, contact_b, contact_a),
        ).fetchone()
        return dict(row) if row else None

    def list_all(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM warm_edges ORDER BY strength DESC"
        )]

    def list_for_contact(self, contact_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM warm_edges WHERE contact_a = ? OR contact_b = ? ORDER BY strength DESC",
            (contact_id, contact_id),
        )]


class PolicyRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def current(self) -> dict | None:
        row = self.conn.execute(
            "SELECT version, policy FROM policies ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return {"version": row["version"], "policy": json.loads(row["policy"])}

    def insert(self, version: int, policy: dict, source: str = "initial") -> None:
        self.conn.execute(
            "INSERT INTO policies (version, policy, source) VALUES (?, ?, ?)",
            (version, json.dumps(policy), source),
        )

    def list_versions(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT version, policy, created_at, source FROM policies ORDER BY version DESC"
        )]
