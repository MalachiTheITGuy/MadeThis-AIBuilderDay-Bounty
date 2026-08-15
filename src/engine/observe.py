"""OBSERVE: outcome ingestion (PLAN.md block 5).

Handles both synthetic (deterministic) and manual outcome recording.
The synthetic feed generates deterministic reply rates and timing based
on action metadata — no network calls, no randomness.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, UTC

from src.domain.enums import OutcomeResult
from src.domain.models import Outcome


# Deterministic outcome mapping by action type and channel.
# In simulation, outcomes follow predictable patterns for demo reproducibility.
_SYNTHETIC_OUTCOMES: dict[str, dict[str, OutcomeResult]] = {
    "OUTREACH_EMAIL": {
        "default": OutcomeResult.REPLY,
        "warm": OutcomeResult.MEETING,
        "cold": OutcomeResult.NO_RESPONSE,
    },
    "LINKEDIN_CONNECT": {
        "default": OutcomeResult.POSITIVE,
        "warm": OutcomeResult.REPLY,
        "cold": OutcomeResult.NEUTRAL,
    },
    "INTRO_REQUEST": {
        "default": OutcomeResult.REPLY,
        "warm": OutcomeResult.MEETING,
        "cold": OutcomeResult.NEUTRAL,
    },
    "FOLLOW_UP": {
        "default": OutcomeResult.NEUTRAL,
        "warm": OutcomeResult.REPLY,
        "cold": OutcomeResult.NO_RESPONSE,
    },
}


def record_outcome(conn: sqlite3.Connection, outcome: Outcome) -> None:
    """Record a single outcome against an action.

    Updates the action status to SENT (if not already) and inserts an outcome
    row into the outcomes table. A MEETING outcome marks the linked
    opportunity WON with a simulated ARR from its segment prior (Issue #45).
    """
    # Ensure action exists and is in a valid state
    row = conn.execute(
        "SELECT id, status, action_type, contact_id, opportunity_id FROM actions WHERE id = ?",
        (outcome.action_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Action not found: {outcome.action_id}")

    # Update action status if still PROPOSED/APPROVED
    if row["status"] in ("PROPOSED", "APPROVED"):
        conn.execute(
            "UPDATE actions SET status = 'SENT' WHERE id = ?",
            (outcome.action_id,),
        )

    # Insert outcome
    conn.execute(
        "INSERT INTO outcomes (id, action_id, result, detail, at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            f"out-{outcome.action_id}",
            outcome.action_id,
            outcome.result.value,
            outcome.detail,
            outcome.at.isoformat(),
        ),
    )
    conn.commit()

    # MEETING → mark the opportunity WON with simulated ARR
    if outcome.result == OutcomeResult.MEETING and row["opportunity_id"]:
        from src.engine.revenue import mark_won
        mark_won(conn, row["opportunity_id"])


def synthesize_outcome(
    conn: sqlite3.Connection,
    action_id: str,
    warmth: str = "default",
) -> Outcome:
    """Generate a deterministic synthetic outcome for an action.

    Looks up the action type and uses the warmth-based mapping to produce
    a predictable outcome for demo/testing.
    """
    row = conn.execute(
        "SELECT action_type FROM actions WHERE id = ?",
        (action_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Action not found: {action_id}")

    action_type = row["action_type"]
    mapping = _SYNTHETIC_OUTCOMES.get(action_type, {})
    result = mapping.get(warmth, mapping.get("default", OutcomeResult.NEUTRAL))

    outcome = Outcome(
        action_id=action_id,
        result=result,
        detail=f"synthetic:{action_type}:{warmth}",
        at=datetime.now(UTC),
    )
    record_outcome(conn, outcome)
    return outcome


def poll_synthetic_outcomes(conn: sqlite3.Connection) -> list[Outcome]:
    """Return all recorded outcomes (for demo replay / leaderboard).

    This is a read-only query — it does not generate new outcomes.
    """
    rows = conn.execute(
        "SELECT action_id, result, detail, at FROM outcomes "
        "ORDER BY at DESC"
    ).fetchall()
    return [
        Outcome(
            action_id=r["action_id"],
            result=OutcomeResult(r["result"]),
            detail=r["detail"] or "",
            at=datetime.fromisoformat(r["at"]),
        )
        for r in rows
    ]
