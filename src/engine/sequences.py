"""Multi-touch sequence intelligence (Issue #44, P2-5).

Real GTM is sequences, not one-shot emails. A sequence = ordered steps with
delay windows and channel rules. The loop learns the cadence itself:
- Thompson sampling over sequence stats (same Beta-Bernoulli as variants).
- Stop rules: a REPLY/MEETING mid-sequence stops it and upgrades warmth
  (remaining cold steps cancel; the path switches to intro-request).
- Policy timing deltas shift *every* step's spacing, so a "bad_timing"
  rejection re-tunes the whole cadence.

Public surface:
    select_sequence(conn, segment, rng) -> dict       # Thompson-sampled sequence
    next_step(conn, sequence_id, opportunity_id) -> dict | None  # next pending step or None
    step_delay_days(conn, sequence_id, step_order) -> int  # policy-tuned spacing
    apply_sequence_outcome(conn, action_id, result) -> dict  # advance/stop + warmth
"""

from __future__ import annotations

import json
import random
import sqlite3

from src.domain.enums import OutcomeResult

_SUCCESS_RESULTS = {
    OutcomeResult.REPLY,
    OutcomeResult.MEETING,
    OutcomeResult.POSITIVE,
}


# ---------------------------------------------------------------------------
# Thompson-sampled sequence selection
# ---------------------------------------------------------------------------

def select_sequence(conn: sqlite3.Connection, segment: str, rng: random.Random | None = None) -> dict:
    """Pick a sequence for a segment via Thompson sampling over its stats."""
    _rng = rng if rng is not None else random.Random()
    rows = conn.execute(
        "SELECT * FROM sequences WHERE segment = ?", (segment,)
    ).fetchall()
    if not rows:
        rows = conn.execute("SELECT * FROM sequences").fetchall()
    if not rows:
        raise ValueError("No sequences seeded")

    best_sample = -1.0
    best = None
    for row in rows:
        stats = json.loads(row["stats"])
        sent = stats.get("sent", 0)
        successes = stats.get("replies", 0) + stats.get("meetings", 0)
        alpha = 1 + successes
        beta = 1 + max(0, sent - successes)
        sample = _rng.betavariate(alpha, beta)
        if sample > best_sample:
            best_sample = sample
            best = dict(row)
            best["stats"] = stats
    assert best is not None
    return best


def get_steps(conn: sqlite3.Connection, sequence_id: str) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM sequence_steps WHERE sequence_id = ? ORDER BY step_order",
            (sequence_id,),
        ).fetchall()
    ]


# ---------------------------------------------------------------------------
# Policy-tuned step spacing
# ---------------------------------------------------------------------------

def step_delay_days(conn: sqlite3.Connection, sequence_id: str, step_order: int) -> int:
    """Base delay for a step, scaled by the policy's timing_prior shift.

    A rejection with reason 'bad_timing' applies timing_prior_adjustment,
    which shifts every future step's spacing (the learned cadence).
    """
    step = conn.execute(
        "SELECT delay_days FROM sequence_steps WHERE sequence_id = ? AND step_order = ?",
        (sequence_id, step_order),
    ).fetchone()
    base = step["delay_days"] if step else 3

    policy = conn.execute(
        "SELECT policy FROM policies ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if policy is None:
        return base
    data = json.loads(policy["policy"])
    adjust = data.get("timing_prior_adjustment", 0.0)
    # Negative adjustment → tighter cadence (better timing). Min 1 day.
    return max(1, int(round(base * (1.0 + adjust))))


# ---------------------------------------------------------------------------
# Sequence advancement / stop rules
# ---------------------------------------------------------------------------

def _last_outcome_for_opportunity(conn: sqlite3.Connection, opportunity_id: str) -> str | None:
    row = conn.execute(
        "SELECT o.result FROM outcomes o "
        "JOIN actions a ON a.id = o.action_id "
        "WHERE a.opportunity_id = ? ORDER BY o.at DESC LIMIT 1",
        (opportunity_id,),
    ).fetchone()
    return row["result"] if row else None


def next_step(conn: sqlite3.Connection, sequence_id: str, opportunity_id: str) -> dict | None:
    """Return the next pending step for an opportunity, or None if done/stopped.

    Stop rules:
      - No earlier actions yet → step 1.
      - Last outcome is a success (REPLY/MEETING/POSITIVE) → sequence stops.
      - Otherwise advance to the next step after the last scheduled one.
    """
    steps = get_steps(conn, sequence_id)
    if not steps:
        return None

    sent_steps = [
        r["step_index"]
        for r in conn.execute(
            "SELECT step_index FROM actions WHERE sequence_id = ? AND opportunity_id = ?",
            (sequence_id, opportunity_id),
        ).fetchall()
    ]

    last_result = _last_outcome_for_opportunity(conn, opportunity_id)
    if last_result is not None:
        try:
            result = OutcomeResult(last_result)
        except ValueError:
            result = None
        if result in _SUCCESS_RESULTS:
            return None  # success stops the sequence

    last_step = max(sent_steps) if sent_steps else 0
    for step in steps:
        if step["step_order"] > last_step:
            return step
    return None


def apply_sequence_outcome(conn: sqlite3.Connection, action_id: str, result: OutcomeResult) -> dict:
    """Process an outcome against a sequence step.

    Returns {'advanced': bool, 'stopped': bool, 'warmth_upgraded': bool}.
    - A success stops the sequence and upgrades the contact's warmth.
    - A NO_RESPONSE/neutral advances to the next step.
    - Sequence stats are updated for future Thompson sampling.
    """
    action = conn.execute(
        "SELECT sequence_id, step_index, contact_id FROM actions WHERE id = ?",
        (action_id,),
    ).fetchone()
    if action is None or not action["sequence_id"]:
        return {"advanced": False, "stopped": False, "warmth_upgraded": False}

    seq = conn.execute(
        "SELECT stats FROM sequences WHERE sequence_id = ?",
        (action["sequence_id"],),
    ).fetchone()
    if seq is None:
        return {"advanced": False, "stopped": False, "warmth_upgraded": False}

    stats = json.loads(seq["stats"])
    stats["sent"] = stats.get("sent", 0) + 1
    if result in _SUCCESS_RESULTS:
        stats["replies"] = stats.get("replies", 0) + 1
    conn.execute(
        "UPDATE sequences SET stats = ? WHERE sequence_id = ?",
        (json.dumps(stats), action["sequence_id"]),
    )
    conn.commit()

    if result in _SUCCESS_RESULTS:
        # Stop the sequence + upgrade warmth to REPLIED
        conn.execute(
            "UPDATE contacts SET warmth = 'replied' WHERE id = ?",
            (action["contact_id"],),
        )
        conn.commit()
        return {"advanced": False, "stopped": True, "warmth_upgraded": True}

    # Non-success → check whether more steps remain for this sequence
    remaining = conn.execute(
        "SELECT COUNT(*) AS n FROM sequence_steps WHERE sequence_id = ? AND step_order > ?",
        (action["sequence_id"], action["step_index"]),
    ).fetchone()["n"]
    return {"advanced": remaining > 0, "stopped": remaining == 0, "warmth_upgraded": False}
