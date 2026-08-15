"""DECIDE: next-best-action selection (PLAN.md block 3).

Thompson sampling over playbook experiments + warm-graph action typing.

Public surface:
    choose_next_best_action(conn, opportunity, rng) -> PlannedAction
    select_variant(conn, segment, rng) -> Experiment   # Beta-Bernoulli sampling
    action_type_for_warmth(warmth) -> ActionType
"""

from __future__ import annotations

import json
import random
import sqlite3

from ..domain.enums import ActionType, Channel, TimingSlot, WarmthSignal
from ..domain.models import Experiment, PlannedAction, Signal


def action_type_for_warmth(warmth: str | WarmthSignal) -> ActionType:
    """Select action type based on relationship warmth.

    Warm contacts (replied, met) → INTRO_REQUEST (leverage the relationship).
    Cold/engaged contacts → OUTREACH_EMAIL or LINKEDIN_CONNECT (build rapport).
    """
    w = warmth if isinstance(warmth, WarmthSignal) else WarmthSignal(warmth)
    if w in (WarmthSignal.REPLIED, WarmthSignal.MET):
        return ActionType.INTRO_REQUEST
    return ActionType.OUTREACH_EMAIL


def select_variant(conn: sqlite3.Connection, segment: str, rng: random.Random) -> Experiment:
    """Pick a playbook variant using Thompson sampling (Beta-Bernoulli).

    Each variant's success rate is modeled as Beta(alpha, beta) where:
    - alpha = 1 + replies + meetings  (successes)
    - beta  = 1 + sent - replies - meetings  (failures)

    We sample from each variant's posterior and pick the argmax.
    With seeded RNG this is fully deterministic.
    """
    rows = conn.execute(
        "SELECT variant_id, segment, template, channel, timing, tone, "
        "personalization_depth, stats FROM experiments WHERE segment = ?",
        (segment,),
    ).fetchall()

    if not rows:
        # Fallback: pick any variant
        rows = conn.execute(
            "SELECT variant_id, segment, template, channel, timing, tone, "
            "personalization_depth, stats FROM experiments"
        ).fetchall()

    best_sample = -1.0
    best_exp = None

    for row in rows:
        stats = json.loads(row["stats"])
        sent = stats.get("sent", 0)
        replies = stats.get("replies", 0)
        meetings = stats.get("meetings", 0)

        # Beta posterior parameters
        alpha = 1 + replies + meetings
        beta = 1 + sent - replies - meetings
        if beta < 1:
            beta = 1

        # Thompson sample
        sample = rng.betavariate(alpha, beta)
        if sample > best_sample:
            best_sample = sample
            best_exp = Experiment(
                variant_id=row["variant_id"],
                segment=row["segment"],
                template=row["template"],
                channel=Channel(row["channel"]),
                timing=TimingSlot(row["timing"]),
                tone=row["tone"],
                personalization_depth=row["personalization_depth"],
                stats=stats,
            )

    assert best_exp is not None, "No experiments found"
    return best_exp


def _get_company_segment(conn: sqlite3.Connection, company_id: str) -> str:
    row = conn.execute("SELECT segment FROM companies WHERE id = ?", (company_id,)).fetchone()
    return row["segment"] if row else "unknown"


def _get_warmth(conn: sqlite3.Connection, company_id: str) -> str:
    """Get the best warmth level among contacts at this company."""
    row = conn.execute(
        "SELECT warmth FROM contacts WHERE company_id = ? ORDER BY "
        "CASE warmth WHEN 'replied' THEN 4 WHEN 'met' THEN 3 WHEN 'engaged' THEN 2 ELSE 1 END DESC LIMIT 1",
        (company_id,),
    ).fetchone()
    return row["warmth"] if row else "cold"


def _get_warm_intro(conn: sqlite3.Connection, company_id: str) -> dict | None:
    """Find a warm-graph intro path for this company's contacts.

    Returns dict with connection name and path info, or None.
    """
    # Find contacts at this company
    contacts = conn.execute(
        "SELECT id, name FROM contacts WHERE company_id = ?", (company_id,)
    ).fetchall()
    if not contacts:
        return None

    for contact in contacts:
        # Check warm edges from this contact
        edges = conn.execute(
            "SELECT we.contact_b, we.strength, c.name FROM warm_edges we "
            "JOIN contacts c ON c.id = we.contact_b "
            "WHERE we.contact_a = ? AND we.strength >= 0.4 "
            "UNION "
            "SELECT we.contact_a, we.strength, c.name FROM warm_edges we "
            "JOIN contacts c ON c.id = we.contact_a "
            "WHERE we.contact_b = ? AND we.strength >= 0.4",
            (contact["id"], contact["id"]),
        ).fetchall()
        if edges:
            best = max(edges, key=lambda e: e["strength"])
            return {
                "connection_name": best["name"],
                "connection_id": best[0],
                "strength": best["strength"],
                "via": contact["name"],
            }
    return None


def choose_next_best_action(
    conn: sqlite3.Connection,
    opportunity: dict,
    rng: random.Random | None = None,
) -> PlannedAction:
    """Select the next best action for an opportunity.

    Combines Thompson-sampled variant selection with warm-graph action typing.
    """
    _rng = rng if rng is not None else random.Random()

    segment = _get_company_segment(conn, opportunity["company_id"])
    variant = select_variant(conn, segment, _rng)

    warmth = _get_warmth(conn, opportunity["company_id"])
    action_type = action_type_for_warmth(warmth)

    # Override action type if warm intro is available
    intro = _get_warm_intro(conn, opportunity["company_id"])
    if intro and action_type == ActionType.OUTREACH_EMAIL:
        action_type = ActionType.INTRO_REQUEST

    # Build expected effect description
    stats = variant.stats
    total = stats.get("sent", 0)
    replies = stats.get("replies", 0)
    reply_rate = (replies / total * 100) if total > 0 else 0.0

    expected_effect = (
        f"Variant {variant.variant_id}: {variant.tone.value} {variant.channel.value} "
        f"at {variant.timing.value}. Historical reply rate: {reply_rate:.0f}% "
        f"({replies}/{total} sent)."
    )
    if intro:
        expected_effect += f" Warm intro via {intro['connection_name']} (strength={intro['strength']:.1f})."

    return PlannedAction(
        action_type=action_type,
        variant_id=variant.variant_id,
        channel=variant.channel,
        timing=variant.timing,
        segment=segment,
        expected_effect=expected_effect,
        confidence=min(0.95, 0.3 + reply_rate / 100 * 0.7),
    )
