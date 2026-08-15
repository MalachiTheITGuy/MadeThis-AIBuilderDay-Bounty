"""Revenue attribution — simulated ARR pipeline view (Issue #45, P2-6).

Closes the attribution gap: the loop proves learning via reply/meeting rates,
but the winning metric is revenue. This module:
1. Marks an opportunity WON with a deterministic ARR from segment priors when
   a MEETING outcome lands (simulated — no real money, data-safety rule D1).
2. Pipeline funnel: QUALIFIED → PROPOSED → SENT → OUTCOME → WON, with counts
   and total ARR per stage.
3. Attribution: ARR attributed per variant, channel, segment, action type,
   and policy version — answers "which experiment actually makes money".
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, UTC

from src.config import DEAL_SIZES


# ---------------------------------------------------------------------------
# Won-opportunity marking
# ---------------------------------------------------------------------------

def mark_won(conn: sqlite3.Connection, opportunity_id: str) -> dict | None:
    """Mark an opportunity WON with a deterministic ARR from its segment prior.

    Returns the updated opportunity row, or None if the opportunity doesn't exist.
    """
    row = conn.execute(
        "SELECT id, arr, won_at, pipeline_stage FROM opportunities WHERE id = ?",
        (opportunity_id,),
    ).fetchone()
    if row is None:
        return None
    if row["pipeline_stage"] == "WON":
        return dict(row)

    segment = conn.execute(
        "SELECT co.segment FROM opportunities o "
        "JOIN companies co ON co.id = o.company_id WHERE o.id = ?",
        (opportunity_id,),
    ).fetchone()
    arr = DEAL_SIZES.get(segment["segment"], 10000) if segment else 10000

    conn.execute(
        "UPDATE opportunities SET won_at = ?, arr = ?, pipeline_stage = 'WON' WHERE id = ?",
        (datetime.now(UTC).isoformat(), arr, opportunity_id),
    )
    conn.commit()
    return conn.execute(
        "SELECT * FROM opportunities WHERE id = ?", (opportunity_id,)
    ).fetchone()


# ---------------------------------------------------------------------------
# Pipeline funnel
# ---------------------------------------------------------------------------

def pipeline(conn: sqlite3.Connection) -> list[dict]:
    """Funnel stages with counts and total ARR for WON opportunities."""
    stages = ["QUALIFIED", "PROPOSED", "SENT", "OUTCOME", "WON"]
    funnel = []
    for stage in stages:
        if stage == "WON":
            row = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(arr), 0) AS arr "
                "FROM opportunities WHERE pipeline_stage = 'WON'"
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS n, 0 AS arr FROM opportunities "
                "WHERE pipeline_stage = ? OR pipeline_stage = ''", (stage,)
            ).fetchone()
        funnel.append({
            "stage": stage,
            "count": row["n"],
            "arr": round(row["arr"], 2),
        })
    return funnel


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------

def attribution(conn: sqlite3.Connection) -> dict:
    """ARR attributed per variant, channel, segment, action type, policy version.

    Attribution rule: a WON opportunity attributes its ARR to every action sent
    against that opportunity (the action's variant/channel/segment/type/version).
    Multiple touches on the same deal each get full credit (simplified
    single-touch approximation for the demo — not a financial system).
    """
    rows = conn.execute(
        "SELECT a.variant_id, a.channel, a.segment, a.action_type, a.policy_version, "
        "o.arr, o.id AS opp_id FROM actions a "
        "JOIN opportunities o ON o.id = a.opportunity_id "
        "WHERE o.pipeline_stage = 'WON'"
    ).fetchall()

    dims = {
        "variant": {},
        "channel": {},
        "segment": {},
        "action_type": {},
        "policy_version": {},
    }
    for r in rows:
        arr = r["arr"] or 0.0
        key_map = {
            "variant": r["variant_id"] or "unknown",
            "channel": r["channel"] or "unknown",
            "segment": r["segment"] or "unknown",
            "action_type": r["action_type"] or "unknown",
            "policy_version": str(r["policy_version"]) if r["policy_version"] is not None else "0",
        }
        for dim, key in key_map.items():
            bucket = dims[dim].setdefault(key, {"arr": 0.0, "deals": set()})
            bucket["arr"] += arr
            bucket["deals"].add(r["opp_id"])

    result = {}
    for dim, buckets in dims.items():
        result[dim] = sorted(
            [{"key": k, "arr": round(v["arr"], 2), "deals": len(v["deals"])}
             for k, v in buckets.items()],
            key=lambda x: x["arr"],
            reverse=True,
        )
    return result
