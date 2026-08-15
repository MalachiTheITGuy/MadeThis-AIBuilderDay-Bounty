"""Trust & audit surface (Issue #42, P2-3).

Productizes trust — the moat MadeThis lost on:
1. Audit export: complete, replayable trail reconstructing any moment in history.
2. Explain-mode: raw decision_trace + template + policy snapshot per action.
3. PII / safety scrub report: scan drafted bodies/subjects against configured
   PII patterns and banned phrases.
"""

from __future__ import annotations

import json
import sqlite3

from src.config import BANNED_PHRASES, PII_PATTERNS


# ---------------------------------------------------------------------------
# 1. Audit export — complete, replayable trail
# ---------------------------------------------------------------------------

def _serialize_meta(row: sqlite3.Row, key: str, default: str = "{}") -> object:
    raw = row[key] if key in row.keys() else default
    try:
        return json.loads(raw or default)
    except (ValueError, TypeError):
        return raw


def audit_export(conn: sqlite3.Connection) -> dict:
    """Return the complete audit trail: actions with decision traces, guardrail
    results, outcomes, and the human activity log. Reconstructs any moment.
    """
    actions = conn.execute(
        "SELECT a.*, o.score AS opp_score, c.name AS contact_name, "
        "co.name AS company_name "
        "FROM actions a "
        "JOIN opportunities o ON o.id = a.opportunity_id "
        "JOIN contacts c ON c.id = a.contact_id "
        "JOIN companies co ON co.id = c.company_id "
        "ORDER BY a.created_at"
    ).fetchall()

    outcomes = conn.execute(
        "SELECT o.*, a.variant_id FROM outcomes o "
        "JOIN actions a ON a.id = o.action_id ORDER BY o.at"
    ).fetchall()

    activity = conn.execute(
        "SELECT * FROM activity ORDER BY at"
    ).fetchall()

    policies = conn.execute(
        "SELECT * FROM policies ORDER BY version"
    ).fetchall()

    return {
        "schema": "gtm-loop audit v1",
        "exported_at": None,  # set by caller to keep pure-stdlib deterministic
        "actions": [
            {
                "id": r["id"],
                "opportunity_id": r["opportunity_id"],
                "company": r["company_name"],
                "contact": r["contact_name"],
                "action_type": r["action_type"],
                "variant_id": r["variant_id"],
                "channel": r["channel"],
                "timing": r["timing"],
                "mode": r["mode"],
                "status": r["status"],
                "subject": r["subject"],
                "body": r["body"],
                "decision_trace": _serialize_meta(r, "decision_trace"),
                "guardrail_blocks": _serialize_meta(r, "guardrail_blocks", "[]"),
                "cost_units": r["cost_units"],
                "policy_version": r["policy_version"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in actions
        ],
        "outcomes": [
            {
                "id": r["id"],
                "action_id": r["action_id"],
                "variant_id": r["variant_id"],
                "result": r["result"],
                "detail": r["detail"],
                "at": r["at"],
            }
            for r in outcomes
        ],
        "activity": [
            {
                "id": r["id"],
                "at": r["at"],
                "actor": r["actor"],
                "action_id": r["action_id"],
                "event": r["event"],
                "status": r["status"],
                "outcome": r["outcome"],
                "reason": r["reason"],
                "policy_version": r["policy_version"],
                "detail": r["detail"],
            }
            for r in activity
        ],
        "policies": [
            {
                "version": r["version"],
                "policy": _serialize_meta(r, "policy"),
                "created_at": r["created_at"],
                "source": r["source"],
            }
            for r in policies
        ],
    }


# ---------------------------------------------------------------------------
# 2. Explain-mode — full trace for an action
# ---------------------------------------------------------------------------

def explain_action(conn: sqlite3.Connection, action_id: str) -> dict | None:
    """Raw decision trace + template + policy snapshot for one action."""
    action = conn.execute(
        "SELECT a.*, e.template, e.segment AS variant_segment, e.channel AS variant_channel, "
        "e.timing AS variant_timing, e.tone, e.personalization_depth, "
        "c.name AS contact_name, co.name AS company_name "
        "FROM actions a "
        "JOIN experiments e ON e.variant_id = a.variant_id "
        "JOIN contacts c ON c.id = a.contact_id "
        "JOIN companies co ON co.id = c.company_id "
        "WHERE a.id = ?",
        (action_id,),
    ).fetchone()
    if action is None:
        return None

    policy = conn.execute(
        "SELECT version, policy, source FROM policies WHERE version = ?",
        (action["policy_version"],),
    ).fetchone()

    outcomes = conn.execute(
        "SELECT * FROM outcomes WHERE action_id = ?", (action_id,)
    ).fetchall()

    return {
        "action_id": action_id,
        "company": action["company_name"],
        "contact": action["contact_name"],
        "subject": action["subject"],
        "body": action["body"],
        "status": action["status"],
        "mode": action["mode"],
        "decision_trace": _serialize_meta(action, "decision_trace"),
        "guardrail_blocks": _serialize_meta(action, "guardrail_blocks", "[]"),
        "template": action["template"],
        "variant": {
            "variant_id": action["variant_id"],
            "segment": action["variant_segment"],
            "channel": action["variant_channel"],
            "timing": action["variant_timing"],
            "tone": action["tone"],
            "personalization_depth": action["personalization_depth"],
        },
        "policy_snapshot": {
            "version": policy["version"] if policy else action["policy_version"],
            "policy": _serialize_meta(policy, "policy") if policy else None,
            "source": policy["source"] if policy else None,
        },
        "outcomes": [
            {"result": r["result"], "detail": r["detail"], "at": r["at"]}
            for r in outcomes
        ],
    }


# ---------------------------------------------------------------------------
# 3. PII / safety scrub report
# ---------------------------------------------------------------------------

def pii_report(conn: sqlite3.Connection) -> dict:
    """Scan all drafted bodies/subjects for PII patterns + banned phrases.

    Returns violations keyed with actionable action IDs.
    """
    rows = conn.execute(
        "SELECT id, subject, body, status FROM actions ORDER BY created_at"
    ).fetchall()

    violations = []
    for r in rows:
        subject = r["subject"] or ""
        body = r["body"] or ""
        combined_lower = (subject + " " + body).lower()
        hits: list[str] = []
        for pattern in PII_PATTERNS:
            if pattern in combined_lower:
                hits.append(f"pii:{pattern}")
        for phrase in BANNED_PHRASES:
            if phrase in combined_lower:
                hits.append(f"banned:{phrase}")
        if hits:
            violations.append({
                "action_id": r["id"],
                "status": r["status"],
                "violations": hits,
            })

    return {
        "checked_actions": len(rows),
        "violations": violations,
        "pii_patterns": list(PII_PATTERNS),
        "banned_phrases": list(BANNED_PHRASES),
    }
