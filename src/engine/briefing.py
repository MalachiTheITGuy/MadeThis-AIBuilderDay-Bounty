"""Loop Digest: evidence-backed weekly briefing (Issue #40, P2-1).

A digest of what the loop actually changed and why — built from real stored
data, never hardcoded numbers:
1. What ran: N actions sent across channels/segments this period.
2. What changed and why: leaderboard shifts, policy changes + the human
   decision that caused them, warm-graph movements.
3. What needs attention: approval queue, budget headroom, guardrail blocks.
4. Suggested actions: rules-based recommendations from the real data.

Pure stdlib; reads the SQLite store directly.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, UTC

from src.config import DAILY_SEND_BUDGET, WEEKLY_SEND_BUDGET
from src.domain.enums import OutcomeResult

_SUCCESS_RESULTS = {
    OutcomeResult.REPLY,
    OutcomeResult.MEETING,
    OutcomeResult.POSITIVE,
}

_PERIOD_DAYS = {"day": 1, "week": 7}


def _since(period: str) -> str:
    days = _PERIOD_DAYS.get(period, 7)
    since = datetime.now(UTC) - timedelta(days=days)
    return since.isoformat()


# ---------------------------------------------------------------------------
# Section 1: What ran
# ---------------------------------------------------------------------------

def _what_ran(conn: sqlite3.Connection, since_iso: str) -> dict:
    rows = conn.execute(
        "SELECT channel, COUNT(*) AS n FROM actions WHERE created_at >= ? "
        "GROUP BY channel ORDER BY n DESC",
        (since_iso,),
    ).fetchall()
    total = sum(r["n"] for r in rows)
    return {
        "total_actions": total,
        "by_channel": {r["channel"]: r["n"] for r in rows},
    }


# ---------------------------------------------------------------------------
# Section 2: What changed and why
# ---------------------------------------------------------------------------

def _leaderboard_shifts(conn: sqlite3.Connection, since_iso: str) -> list[dict]:
    """Per-variant reply/meeting rates this period + raw counts.

    Uses the outcomes table (the real outcome history) rather than the
    cumulative experiments.stats, so the numbers are period-scoped.
    """
    rows = conn.execute(
        "SELECT a.variant_id, o.result FROM outcomes o "
        "JOIN actions a ON a.id = o.action_id WHERE o.at >= ?",
        (since_iso,),
    ).fetchall()
    per_variant: dict[str, dict[str, int]] = {}
    for r in rows:
        stats = per_variant.setdefault(r["variant_id"], {"sent": 0, "replies": 0, "meetings": 0})
        stats["sent"] += 1
        try:
            result = OutcomeResult(r["result"])
        except ValueError:
            continue
        if result in (OutcomeResult.REPLY,):
            stats["replies"] += 1
        elif result in (OutcomeResult.MEETING,):
            stats["meetings"] += 1
        elif result in _SUCCESS_RESULTS:
            stats["replies"] += 1  # POSITIVE counts as a reply-level success

    shifts = []
    for variant, s in sorted(per_variant.items()):
        sent = s["sent"]
        success = s["replies"] + s["meetings"]
        shifts.append({
            "variant_id": variant,
            "sent": sent,
            "replies": s["replies"],
            "meetings": s["meetings"],
            "success_rate": round(success / sent, 3) if sent else 0.0,
        })
    return shifts


def _policy_changes(conn: sqlite3.Connection, since_iso: str) -> list[dict]:
    """Policy versions created this period, with the human decision that caused them."""
    rows = conn.execute(
        "SELECT version, policy, created_at, source FROM policies "
        "WHERE created_at >= ? ORDER BY version",
        (since_iso,),
    ).fetchall()
    changes = []
    for r in rows:
        changes.append({
            "version": r["version"],
            "source": r["source"],
            "created_at": r["created_at"],
        })
    return changes


def _warm_movements(conn: sqlite3.Connection, since_iso: str) -> list[dict]:
    """Warm edges touched this period + the outcome that did it."""
    rows = conn.execute(
        "SELECT contact_a, contact_b, strength, last_interaction, source "
        "FROM warm_edges WHERE last_interaction >= ? ORDER BY last_interaction",
        (since_iso,),
    ).fetchall()
    return [
        {
            "contact_a": r["contact_a"],
            "contact_b": r["contact_b"],
            "strength": r["strength"],
            "last_interaction": r["last_interaction"],
            "source": r["source"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Section 3: What needs attention
# ---------------------------------------------------------------------------

def _needs_attention(conn: sqlite3.Connection, since_iso: str) -> dict:
    queue = conn.execute(
        "SELECT COUNT(*) AS n FROM actions WHERE status = 'PROPOSED'"
    ).fetchone()["n"]

    sent = conn.execute(
        "SELECT COUNT(*) AS n FROM actions WHERE created_at >= ? AND status = 'SENT'",
        (since_iso,),
    ).fetchone()["n"]

    guardrails = conn.execute(
        "SELECT COUNT(*) AS n FROM activity WHERE event = 'propose' "
        "AND reason LIKE '%guardrail%' AND at >= ?",
        (since_iso,),
    ).fetchone()["n"]

    return {
        "pending_approval": queue,
        "actions_sent_this_period": sent,
        "daily_budget": DAILY_SEND_BUDGET,
        "weekly_budget": WEEKLY_SEND_BUDGET,
        "budget_headroom": max(0, WEEKLY_SEND_BUDGET - sent),
        "guardrail_blocks": guardrails,
    }


# ---------------------------------------------------------------------------
# Section 4: Suggested actions (rules-based on real data)
# ---------------------------------------------------------------------------

def _suggestions(shifts: list[dict], attention: dict) -> list[str]:
    suggestions: list[str] = []
    if shifts:
        worst = min(shifts, key=lambda s: s["success_rate"])
        if worst["success_rate"] < 0.15 and worst["sent"] >= 5:
            suggestions.append(
                f"{worst['variant_id']} is underperforming ({worst['sent']} sent, "
                f"{worst['success_rate']:.0%} success) — consider pausing it."
            )
        best = max(shifts, key=lambda s: s["success_rate"])
        if best["success_rate"] >= 0.4 and best["sent"] >= 3:
            suggestions.append(
                f"{best['variant_id']} leads with {best['success_rate']:.0%} success "
                f"({best['sent']} sent) — increase its allocation."
            )
    if attention["pending_approval"]:
        suggestions.append(
            f"{attention['pending_approval']} action(s) await approval in the queue."
        )
    if attention["budget_headroom"] <= 0:
        suggestions.append("Weekly send budget exhausted — consider raising WEEKLY_SEND_BUDGET.")
    elif attention["budget_headroom"] < attention["daily_budget"]:
        suggestions.append(
            f"Budget headroom is tight ({attention['budget_headroom']} left this week)."
        )
    if attention["guardrail_blocks"]:
        suggestions.append(
            f"{attention['guardrail_blocks']} guardrail block(s) fired this period — review scope."
        )
    return suggestions


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def briefing(conn: sqlite3.Connection, period: str = "week") -> dict:
    """Build the evidence-backed briefing digest for the given period."""
    since = _since(period)
    shifts = _leaderboard_shifts(conn, since)
    attention = _needs_attention(conn, since)
    return {
        "period": period,
        "generated_at": datetime.now(UTC).isoformat(),
        "what_ran": _what_ran(conn, since),
        "leaderboard_shifts": shifts,
        "policy_changes": _policy_changes(conn, since),
        "warm_movements": _warm_movements(conn, since),
        "needs_attention": attention,
        "suggested_actions": _suggestions(shifts, attention),
    }
