"""LEARN: behavior change, not note-taking (PLAN.md block 6, §4).

Three mechanisms:
1. Thompson-sampled experiment stats updated from outcomes.
2. Feedback→policy map: user edits/rejections mutate policy state (versioned).
3. Warm-graph edge updates from outcomes.

Planned public surface:
    apply_outcome(conn, outcome) -> LearningDelta
    apply_feedback(conn, action_id, reason | edits) -> LearningDelta
    rollback_policy(conn) -> int   # returns restored version
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, UTC

from src.domain.enums import OutcomeResult, RejectionReason
from src.domain.models import EdgeDelta, LearningDelta, Outcome, PolicyDelta


# ---------------------------------------------------------------------------
# Feedback → policy delta mapping (PLAN.md §4.2)
# ---------------------------------------------------------------------------

_REJECTION_POLICY_MAP: dict[str, list[PolicyDelta]] = {
    RejectionReason.TOO_LONG.value: [
        PolicyDelta(field="brevity", delta=0.1, source="rejection:too_long"),
    ],
    RejectionReason.TOO_SALESY.value: [
        PolicyDelta(field="tone_assertiveness", delta=-0.1, source="rejection:too_salesy"),
        PolicyDelta(field="softener_phrases", delta=0.05, source="rejection:too_salesy"),
    ],
    RejectionReason.MISSING_PERSONALIZATION.value: [
        PolicyDelta(field="personalization_depth", delta=1, source="rejection:missing_personalization"),
    ],
    RejectionReason.WRONG_CHANNEL.value: [
        PolicyDelta(field="channel_prior_adjustment", delta=-0.05, source="rejection:wrong_channel"),
    ],
    RejectionReason.BAD_TIMING.value: [
        PolicyDelta(field="timing_prior_adjustment", delta=-0.05, source="rejection:bad_timing"),
    ],
    RejectionReason.WRONG_TARGET.value: [
        PolicyDelta(field="icp_fit_threshold", delta=0.05, source="rejection:wrong_target"),
    ],
}


# ---------------------------------------------------------------------------
# Variant stats update
# ---------------------------------------------------------------------------

def _update_variant_stats(conn: sqlite3.Connection, variant_id: str, result: OutcomeResult) -> None:
    """Increment the relevant counter in the variant's stats JSON."""
    row = conn.execute(
        "SELECT stats FROM experiments WHERE variant_id = ?",
        (variant_id,),
    ).fetchone()
    if row is None:
        return

    stats = json.loads(row["stats"])

    # Increment sent on any outcome (action was sent)
    stats["sent"] = stats.get("sent", 0) + 1

    # Map outcome result to stat keys
    result_map = {
        OutcomeResult.REPLY: "replies",
        OutcomeResult.MEETING: "meetings",
        OutcomeResult.POSITIVE: "positive",
        OutcomeResult.NEUTRAL: "neutral",
        OutcomeResult.NEGATIVE: "negative",
        OutcomeResult.REJECTION: "rejections",
        OutcomeResult.UNSUB: "unsubs",
        OutcomeResult.NO_RESPONSE: "no_response",
    }
    key = result_map.get(result)
    if key:
        stats[key] = stats.get(key, 0) + 1

    conn.execute(
        "UPDATE experiments SET stats = ? WHERE variant_id = ?",
        (json.dumps(stats), variant_id),
    )


# ---------------------------------------------------------------------------
# Policy management
# ---------------------------------------------------------------------------

def _get_current_policy(conn: sqlite3.Connection) -> dict | None:
    """Get the latest policy version."""
    row = conn.execute(
        "SELECT version, policy FROM policies ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return {"version": row["version"], "policy": json.loads(row["policy"])}


def _apply_policy_deltas(conn: sqlite3.Connection, deltas: list[PolicyDelta]) -> int:
    """Apply policy deltas and create a new version. Returns new version number."""
    current = _get_current_policy(conn)
    if current is None:
        return 0

    policy = current["policy"]
    new_version = current["version"] + 1

    for delta in deltas:
        current_val = policy.get(delta.field, 0.0)
        if isinstance(current_val, (int, float)):
            policy[delta.field] = current_val + delta.delta
        else:
            policy[delta.field] = delta.delta

    conn.execute(
        "INSERT INTO policies (version, policy, source) VALUES (?, ?, ?)",
        (new_version, json.dumps(policy), deltas[0].source if deltas else "apply_feedback"),
    )
    conn.commit()
    return new_version


def rollback_policy(conn: sqlite3.Connection) -> int:
    """Rollback to the previous policy version. Returns restored version number."""
    current = _get_current_policy(conn)
    if current is None or current["version"] <= 1:
        return 0

    # Get the previous version
    prev = conn.execute(
        "SELECT version, policy FROM policies WHERE version = ?",
        (current["version"] - 1,),
    ).fetchone()
    if prev is None:
        return 0

    # Create a new version with the previous policy's content
    new_version = current["version"] + 1
    conn.execute(
        "INSERT INTO policies (version, policy, source) VALUES (?, ?, ?)",
        (new_version, prev["policy"], f"rollback_from:{current['version']}"),
    )
    conn.commit()
    return new_version


# ---------------------------------------------------------------------------
# Warm-graph updates
# ---------------------------------------------------------------------------

def _update_warm_edge(
    conn: sqlite3.Connection,
    contact_a: str,
    contact_b: str,
    delta: float,
    source: str,
) -> None:
    """Update or create a warm edge between two contacts."""
    # Skip if either contact doesn't exist in DB (e.g. "system")
    for cid in (contact_a, contact_b):
        if not conn.execute("SELECT 1 FROM contacts WHERE id = ?", (cid,)).fetchone():
            return

    existing = conn.execute(
        "SELECT id, strength FROM warm_edges WHERE contact_a = ? AND contact_b = ?",
        (contact_a, contact_b),
    ).fetchone()

    if existing:
        new_strength = max(0.0, min(1.0, existing["strength"] + delta))
        conn.execute(
            "UPDATE warm_edges SET strength = ?, last_interaction = ?, source = ? WHERE id = ?",
            (new_strength, datetime.now(UTC).isoformat(), source, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO warm_edges (contact_a, contact_b, strength, direction, last_interaction, source) "
            "VALUES (?, ?, ?, 'outbound', ?, ?)",
            (contact_a, contact_b, max(0.0, min(1.0, 0.5 + delta)), datetime.now(UTC).isoformat(), source),
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_outcome(conn: sqlite3.Connection, outcome: Outcome) -> LearningDelta:
    """Process an outcome: update variant stats, warm edges.

    Returns the LearningDelta describing what changed.
    """
    # Look up the action to find variant_id and contact_id
    row = conn.execute(
        "SELECT variant_id, contact_id FROM actions WHERE id = ?",
        (outcome.action_id,),
    ).fetchone()
    if row is None:
        return LearningDelta()

    variant_id = row["variant_id"]
    contact_id = row["contact_id"]

    # Update variant stats
    _update_variant_stats(conn, variant_id, outcome.result)
    conn.commit()

    # Update warm edge: positive outcomes strengthen, negative weaken
    edge_delta = 0.0
    if outcome.result in (OutcomeResult.REPLY, OutcomeResult.MEETING, OutcomeResult.POSITIVE):
        edge_delta = 0.1
    elif outcome.result in (OutcomeResult.NEGATIVE, OutcomeResult.REJECTION, OutcomeResult.UNSUB):
        edge_delta = -0.1

    warm_deltas: list[EdgeDelta] = []
    if edge_delta != 0.0:
        _update_warm_edge(conn, contact_id, "system", edge_delta, f"outcome:{outcome.result.value}")
        conn.commit()
        warm_deltas.append(EdgeDelta(
            contact_a=contact_id,
            contact_b="system",
            strength_delta=edge_delta,
            source=f"outcome:{outcome.result.value}",
        ))

    return LearningDelta(
        variant_updates={variant_id: {"sent": 1, outcome.result.value: 1}},
        warm_graph_deltas=warm_deltas,
    )


def apply_feedback(
    conn: sqlite3.Connection,
    action_id: str,
    reason: str | None = None,
    edits: dict | None = None,
) -> LearningDelta:
    """Process human feedback: rejection reason → policy delta, or edit → policy delta.

    Returns the LearningDelta describing what changed.
    """
    # Verify action exists
    row = conn.execute("SELECT id FROM actions WHERE id = ?", (action_id,)).fetchone()
    if row is None:
        return LearningDelta()

    policy_deltas: list[PolicyDelta] = []

    if reason and reason in _REJECTION_POLICY_MAP:
        policy_deltas = _REJECTION_POLICY_MAP[reason]
    elif edits:
        # Edit-based policy deltas
        if "personalization_count" in edits:
            delta_val = edits["personalization_count"]
            policy_deltas.append(PolicyDelta(
                field="personalization_depth",
                delta=delta_val,
                source="user_edit",
            ))
        if "tone" in edits:
            policy_deltas.append(PolicyDelta(
                field="tone_assertiveness",
                delta=0.05 if edits["tone"] == "warmer" else -0.05,
                source="user_edit",
            ))

    new_version = 0
    if policy_deltas:
        new_version = _apply_policy_deltas(conn, policy_deltas)

    return LearningDelta(
        policy_deltas=policy_deltas,
        playbook_new_version=new_version,
    )
