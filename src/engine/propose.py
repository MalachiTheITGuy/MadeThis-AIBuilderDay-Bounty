"""PROPOSE: decision-card building for explainability (PLAN.md block 4, §6).

Public surface:
    build_decision_card(conn, action_row, qualification_trace) -> DecisionCard
    persist_trace(conn, action_id, trace: dict) -> None
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..domain.enums import ActionType, Channel, TimingSlot
from ..domain.models import DecisionCard


def build_decision_card(
    conn: sqlite3.Connection,
    action_row: dict[str, Any],
    qualification_trace: dict[str, Any] | None = None,
) -> DecisionCard:
    """Build a full decision card (§6 explainability payload) from an action row.

    The card answers:
    1. What — action type, target, channel, timing, cost
    2. Why — qualification evidence, NBAM reasoning
    3. Evidence — signal payload, contact memory
    4. Guardrails — which rules were checked, pass/fail
    5. What it learned — last feedback/outcome deltas
    6. What happens next — queued follow-up plan
    """
    action_id = action_row["id"]
    action_type = ActionType(action_row["action_type"])
    channel = Channel(action_row["channel"])
    timing = TimingSlot(action_row["timing"])
    cost_units = action_row.get("cost_units", 1)

    # Get contact info
    contact = conn.execute(
        "SELECT name, title, company_id FROM contacts WHERE id = ?",
        (action_row["contact_id"],),
    ).fetchone()
    target = f"{contact['name']} ({contact['title']})" if contact else action_row["contact_id"]

    # Get company info
    company = None
    if contact:
        company = conn.execute(
            "SELECT name, segment FROM companies WHERE id = ?",
            (contact["company_id"],),
        ).fetchone()

    # Qualification evidence (from decision_trace or qualification_trace)
    decision_trace = json.loads(action_row.get("decision_trace", "{}"))
    qual = decision_trace.get("qualification", qualification_trace or {})
    why: list[str] = []
    evidence: list[str] = []

    if qual:
        for note in qual.get("fit_notes", []):
            why.append(note)
        for hit in qual.get("icp_hits", []):
            evidence.append(hit)

    # NBAM reasoning
    variant_id = action_row.get("variant_id", "")
    if variant_id:
        why.append(f"NBAM selected variant: {variant_id}")

    # Signal info
    signal_row = None
    opportunity = conn.execute(
        "SELECT signal_id FROM opportunities WHERE id = ?",
        (action_row["opportunity_id"],),
    ).fetchone()
    if opportunity:
        signal_row = conn.execute(
            "SELECT type, payload FROM signals WHERE id = ?",
            (opportunity["signal_id"],),
        ).fetchone()
    if signal_row:
        payload = json.loads(signal_row["payload"])
        evidence.append(f"Signal: {signal_row['type']} — {json.dumps(payload)}")

    # Guardrail results
    guardrail_blocks = json.loads(action_row.get("guardrail_blocks", "[]"))
    guardrails: list[str] = []
    if guardrail_blocks:
        for block in guardrail_blocks:
            guardrails.append(f"BLOCKED: {block}")
    else:
        guardrails.append("ALL PASSED: budget, rate limits, content, action class")

    # Learned info — check recent outcomes for this variant
    learned: list[str] = []
    if variant_id:
        exp = conn.execute(
            "SELECT stats FROM experiments WHERE variant_id = ?", (variant_id,)
        ).fetchone()
        if exp:
            stats = json.loads(exp["stats"])
            total = stats.get("sent", 0)
            replies = stats.get("replies", 0)
            meetings = stats.get("meetings", 0)
            if total > 0:
                learned.append(f"Variant {variant_id}: {replies}/{total} replied, {meetings} meetings")

    # Recent activity for this contact
    recent_activity = conn.execute(
        "SELECT event, status, reason FROM activity "
        "WHERE action_id IN (SELECT id FROM actions WHERE contact_id = ?) "
        "ORDER BY at DESC LIMIT 3",
        (action_row["contact_id"],),
    ).fetchall()
    for act in recent_activity:
        if act["reason"]:
            learned.append(f"Past feedback: {act['event']} — {act['reason']}")

    # Expected effect
    expected_effect = action_row.get("body", "")[:200] if action_row.get("body") else "No message drafted yet."

    # Next steps
    next_steps = f"If approved: execute via {channel.value} at {timing.value}. "
    next_steps += "If rejected: feedback will update policy for future messages in this segment."

    return DecisionCard(
        action_id=action_id,
        action_type=action_type,
        target=target,
        channel=channel,
        timing=timing,
        cost_units=cost_units,
        why=why,
        evidence=evidence,
        guardrails=guardrails,
        learned=learned,
        next_steps=next_steps,
        expected_effect=expected_effect,
    )


def persist_trace(conn: sqlite3.Connection, action_id: str, trace: dict) -> None:
    """Persist a decision trace JSON blob on the action row."""
    conn.execute(
        "UPDATE actions SET decision_trace = ? WHERE id = ?",
        (json.dumps(trace), action_id),
    )
    conn.commit()
