"""PERMISSION: mode routing, action classes, guardrails (PLAN.md block 4, §5).

Public surface:
    evaluate(conn, action, contact, scope) -> PermissionDecision
    guardrail_checks(conn, action, body) -> list[str]
    within_budget(conn, cost_units) -> bool
    classify_action(action_type, cost_units) -> ActionClass
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, UTC

from ..config import (
    AUTOPILOT_DEFAULT_SCOPE,
    BANNED_PHRASES,
    COST_UNITS_PER_SEND,
    DAILY_SEND_BUDGET,
    HIGH_COST_THRESHOLD_UNITS,
    MAX_FOLLOW_UPS_PER_THREAD,
    MAX_SENDS_PER_CONTACT_PER_DAY,
    MIN_INTERVAL_BETWEEN_CONTACT_ACTIONS_HOURS,
    PII_PATTERNS,
    WEEKLY_SEND_BUDGET,
)
from ..domain.enums import ActionClass, ActionType, Mode
from ..domain.models import PermissionDecision


def classify_action(action_type: str | ActionType, cost_units: int = COST_UNITS_PER_SEND) -> ActionClass:
    """Classify an action into an approval class (PLAN.md §5.2).

    IRREVERSIBLE / EXTERNAL / HIGH_COST → mandatory approval, never auto-executed.
    """
    at = ActionType(action_type) if isinstance(action_type, str) else action_type

    if at in (ActionType.INTRO_REQUEST,):
        return ActionClass.EXTERNAL  # intro requests involve other people

    if cost_units >= HIGH_COST_THRESHOLD_UNITS:
        return ActionClass.HIGH_COST

    return ActionClass.REVERSIBLE


def within_budget(conn: sqlite3.Connection, cost_units: int) -> bool:
    """Check if we're within daily and weekly send budgets."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    week_start = (datetime.now(UTC) - timedelta(days=datetime.now(UTC).weekday())).strftime("%Y-%m-%d")

    daily = conn.execute(
        "SELECT COALESCE(SUM(cost_units), 0) AS total FROM actions "
        "WHERE created_at >= ? AND status != 'BLOCKED'",
        (today,),
    ).fetchone()["total"]

    weekly = conn.execute(
        "SELECT COALESCE(SUM(cost_units), 0) AS total FROM actions "
        "WHERE created_at >= ? AND status != 'BLOCKED'",
        (week_start,),
    ).fetchone()["total"]

    return (daily + cost_units <= DAILY_SEND_BUDGET) and (weekly + cost_units <= WEEKLY_SEND_BUDGET)


def _rate_limit_ok(conn: sqlite3.Connection, contact_id: str) -> bool:
    """Check min interval between actions to the same contact."""
    cutoff = (datetime.now(UTC) - timedelta(hours=MIN_INTERVAL_BETWEEN_CONTACT_ACTIONS_HOURS)).isoformat()
    recent = conn.execute(
        "SELECT COUNT(*) AS n FROM actions WHERE contact_id = ? AND created_at > ?",
        (contact_id, cutoff),
    ).fetchone()["n"]
    return recent == 0


def _follow_up_limit_ok(conn: sqlite3.Connection, contact_id: str) -> bool:
    """Check max follow-ups per thread."""
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM actions WHERE contact_id = ? AND action_type = 'FOLLOW_UP'",
        (contact_id,),
    ).fetchone()["n"]
    return count < MAX_FOLLOW_UPS_PER_THREAD


def _daily_contact_limit_ok(conn: sqlite3.Connection, contact_id: str) -> bool:
    """Check max sends per contact per day."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM actions WHERE contact_id = ? AND created_at >= ? AND status != 'BLOCKED'",
        (contact_id, today),
    ).fetchone()["n"]
    return count < MAX_SENDS_PER_CONTACT_PER_DAY


def guardrail_checks(
    conn: sqlite3.Connection,
    action_type: str,
    contact_id: str,
    cost_units: int,
    body: str = "",
) -> list[str]:
    """Run all guardrail checks. Returns list of block reasons (empty = pass)."""
    blocks: list[str] = []

    # Budget
    if not within_budget(conn, cost_units):
        blocks.append("over_budget: daily or weekly send budget exceeded")

    # Rate limits
    if not _rate_limit_ok(conn, contact_id):
        blocks.append(f"rate_limit: min {MIN_INTERVAL_BETWEEN_CONTACT_ACTIONS_HOURS}h between actions to same contact")

    if not _daily_contact_limit_ok(conn, contact_id):
        blocks.append(f"daily_contact_limit: max {MAX_SENDS_PER_CONTACT_PER_DAY} sends per contact per day")

    if action_type == ActionType.FOLLOW_UP and not _follow_up_limit_ok(conn, contact_id):
        blocks.append(f"follow_up_limit: max {MAX_FOLLOW_UPS_PER_THREAD} follow-ups per thread")

    # Content guardrails
    body_lower = body.lower()
    for phrase in BANNED_PHRASES:
        if phrase in body_lower:
            blocks.append(f"banned_phrase: '{phrase}' found in message body")

    for pattern in PII_PATTERNS:
        if pattern in body_lower:
            blocks.append(f"pii_detected: '{pattern}' found in message body")

    # Action class mandatory approval
    action_class = classify_action(action_type, cost_units)
    if action_class in (ActionClass.IRREVERSIBLE, ActionClass.EXTERNAL, ActionClass.HIGH_COST):
        blocks.append(f"mandatory_approval: action class {action_class.value} requires human approval")

    return blocks


def evaluate(
    conn: sqlite3.Connection,
    action_type: str,
    contact_id: str,
    cost_units: int,
    body: str = "",
    mode: Mode = Mode.PROPOSE,
    scope: dict | None = None,
    channel: str = "EMAIL",
    timing: str = "MORNING",
) -> PermissionDecision:
    """Evaluate whether an action requires approval.

    In PROPOSE mode, everything requires approval.
    In AUTOPILOT mode, actions within scope and guardrails auto-execute.
    Mandatory-approval classes always require approval regardless of mode.
    """
    _scope = scope or AUTOPILOT_DEFAULT_SCOPE
    action_class = classify_action(action_type, cost_units)
    blocks = guardrail_checks(conn, action_type, contact_id, cost_units, body)

    reasons: list[str] = []

    # Mandatory-approval classes always require approval
    if action_class in (ActionClass.IRREVERSIBLE, ActionClass.EXTERNAL, ActionClass.HIGH_COST):
        reasons.append(f"action class {action_class.value} requires approval")

    # Guardrail blocks force approval
    if blocks:
        reasons.append(f"{len(blocks)} guardrail(s) triggered")

    # Propose mode → everything requires approval
    if mode == Mode.PROPOSE:
        reasons.append("propose mode: all actions require human approval")
        return PermissionDecision(
            mode=mode,
            requires_approval=True,
            reasons=reasons,
            guardrail_blocks=blocks,
            action_class=action_class,
        )

    # Autopilot mode → check scope
    if not _scope.get("enabled", False):
        reasons.append("autopilot not enabled")
        return PermissionDecision(
            mode=mode,
            requires_approval=True,
            reasons=reasons,
            guardrail_blocks=blocks,
            action_class=action_class,
        )

    # Check scope constraints
    allowed_segments = _scope.get("allowed_segments", [])
    allowed_channels = _scope.get("allowed_channels", [])
    allowed_timing = _scope.get("allowed_timing", [])
    max_cost = _scope.get("max_cost_units_per_action", 3)

    # Look up contact's segment from DB
    contact_row = conn.execute(
        "SELECT co.segment FROM contacts c JOIN companies co ON co.id = c.company_id WHERE c.id = ?",
        (contact_id,),
    ).fetchone()
    contact_segment = contact_row["segment"] if contact_row else "unknown"

    if allowed_segments and contact_segment not in allowed_segments:
        reasons.append("segment not in autopilot scope")
    if allowed_channels and channel not in allowed_channels:
        reasons.append("channel not in autopilot scope")
    if allowed_timing and timing not in allowed_timing:
        reasons.append("timing not in autopilot scope")
    if cost_units > max_cost:
        reasons.append(f"cost {cost_units} exceeds autopilot max {max_cost}")

    if reasons and not blocks:
        return PermissionDecision(
            mode=mode,
            requires_approval=True,
            reasons=reasons,
            guardrail_blocks=[],
            action_class=action_class,
        )

    # Within scope, no blocks, no mandatory class → auto-execute
    if not reasons and not blocks:
        return PermissionDecision(
            mode=mode,
            requires_approval=False,
            reasons=["autopilot: within scope, no guardrail blocks"],
            guardrail_blocks=[],
            action_class=action_class,
        )

    return PermissionDecision(
        mode=mode,
        requires_approval=True,
        reasons=reasons,
        guardrail_blocks=blocks,
        action_class=action_class,
    )


# --- Kill switch / control state ---------------------------------------------

_CONTROL_STATE: dict[str, str] = {"status": "running"}  # running | paused | stopped


def get_control_status() -> str:
    return _CONTROL_STATE["status"]


def set_control_status(status: str) -> str:
    _CONTROL_STATE["status"] = status
    return _CONTROL_STATE["status"]


def log_activity(
    conn: sqlite3.Connection,
    actor: str,
    action_id: str | None,
    event: str,
    status: str = "",
    outcome: str = "",
    reason: str = "",
    policy_version: int = 0,
    detail: str = "",
) -> None:
    """Append a row to the activity trail."""
    conn.execute(
        "INSERT INTO activity (actor, action_id, event, status, outcome, reason, policy_version, detail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (actor, action_id, event, status, outcome, reason, policy_version, detail),
    )
    conn.commit()
