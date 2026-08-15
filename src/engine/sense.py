"""SENSE: ingest signals and qualify opportunities (PLAN.md block 2).

Public surface:
    ingest_signal(conn, signal: Signal) -> None          # dedupe + persist
    scan(conn) -> list[Signal]                            # local synthetic feed
    qualify(conn, signal: Signal) -> Qualification | None # rule scoring
    create_opportunity(conn, signal, qual) -> Opportunity
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlite3

from ..config import (
    QUALIFY_THRESHOLD, SIGNAL_DEDUPE_WINDOW_HOURS,
    SIGNAL_TYPE_WEIGHTS, STAGE_WEIGHTS, TARGET_SEGMENTS, EMPLOYEE_BRACKETS,
    SIGNAL_PROB_FUNDING, SIGNAL_PROB_PRODUCT, SIGNAL_PROB_HIRING,
    HIRING_EMPLOYEE_THRESHOLD, INTERESTING_TAGS,
)
from ..domain.enums import OpportunityStatus, SignalType
from ..domain.models import Company, Opportunity, Qualification, Signal


def ingest_signal(conn: sqlite3.Connection, signal: Signal) -> bool:
    """Persist a signal after deduplication.

    Returns True if the signal was inserted (not a duplicate), False if skipped.
    Deduplication: same company_id + signal type within the configured window.
    """
    cutoff = (signal.detected_at - timedelta(hours=SIGNAL_DEDUPE_WINDOW_HOURS)).isoformat()
    existing = conn.execute(
        "SELECT id FROM signals WHERE company_id = ? AND type = ? AND detected_at > ?",
        (signal.company_id, signal.type.value, cutoff),
    ).fetchone()
    if existing:
        return False

    conn.execute(
        "INSERT INTO signals (id, company_id, type, payload, detected_at) VALUES (?, ?, ?, ?, ?)",
        (signal.id, signal.company_id, signal.type.value, json.dumps(signal.payload), signal.detected_at.isoformat()),
    )
    conn.commit()
    return True


def scan(conn: sqlite3.Connection) -> list[Signal]:
    """Return all persisted signals (local synthetic feed)."""
    rows = conn.execute("SELECT id, company_id, type, payload, detected_at FROM signals ORDER BY detected_at").fetchall()
    return [
        Signal(
            id=r["id"],
            company_id=r["company_id"],
            type=SignalType(r["type"]),
            payload=json.loads(r["payload"]),
            detected_at=datetime.fromisoformat(r["detected_at"]),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Qualification scoring
# ---------------------------------------------------------------------------


def _score_employees(employees: int) -> float:
    for lo, hi, weight in EMPLOYEE_BRACKETS:
        if lo <= employees < hi:
            return weight
    return 0.2


def qualify(conn: sqlite3.Connection, signal: Signal) -> Qualification | None:
    """Score a signal against firmographic + signal-type rules.

    Returns a Qualification with score and evidence, or None if the company
    doesn't exist in the DB. The caller decides whether the score meets the
    QUALIFY_THRESHOLD to create an Opportunity.
    """
    row = conn.execute(
        "SELECT id, name, segment, stage, employees, tags FROM companies WHERE id = ?",
        (signal.company_id,),
    ).fetchone()
    if not row:
        return None

    company = Company(
        id=row["id"],
        name=row["name"],
        segment=row["segment"],
        stage=row["stage"],
        employees=row["employees"],
        tags=json.loads(row["tags"]),
    )

    fit_notes: list[str] = []
    icp_hits: list[str] = []
    weights: list[float] = []

    # 1. Signal type relevance
    sig_weight = SIGNAL_TYPE_WEIGHTS.get(signal.type.value, 0.3)
    weights.append(sig_weight)
    fit_notes.append(f"Signal type {signal.type.value} (relevance={sig_weight:.1f})")

    # 2. Segment fit
    if company.segment in TARGET_SEGMENTS:
        seg_weight = 0.8
        icp_hits.append(f"Target segment: {company.segment}")
    else:
        seg_weight = 0.3
        fit_notes.append(f"Non-target segment: {company.segment}")
    weights.append(seg_weight)

    # 3. Stage fit
    stage_weight = STAGE_WEIGHTS.get(company.stage, 0.3)
    weights.append(stage_weight)
    fit_notes.append(f"Company stage: {company.stage} (weight={stage_weight:.1f})")

    # 4. Employee count (firmographic)
    emp_weight = _score_employees(company.employees)
    weights.append(emp_weight)
    fit_notes.append(f"Employees: {company.employees} (bracket weight={emp_weight:.1f})")

    # 5. Tag bonus — interesting tags bump the score
    tag_bonus = 0.0
    matched_tags = INTERESTING_TAGS & set(company.tags)
    if matched_tags:
        tag_bonus = min(len(matched_tags) * 0.05, 0.15)
        icp_hits.append(f"Interesting tags: {', '.join(sorted(matched_tags))}")
    weights.append(1.0 + tag_bonus)  # multiplicative small bonus

    # Weighted average
    score = sum(weights) / len(weights)
    score = max(0.0, min(1.0, score))  # clamp to [0, 1]

    return Qualification(
        score=round(score, 3),
        fit_notes=fit_notes,
        icp_hits=icp_hits,
    )


def create_opportunity(conn: sqlite3.Connection, signal: Signal, qual: Qualification) -> Opportunity:
    """Create a QUALIFIED opportunity from a signal + its qualification."""
    opp_id = f"opp-{uuid.uuid4().hex[:12]}"
    opp = Opportunity(
        id=opp_id,
        company_id=signal.company_id,
        signal_id=signal.id,
        status=OpportunityStatus.QUALIFIED,
        score=qual.score,
        fit_notes=qual.fit_notes,
        decision_trace={"qualification": qual.model_dump()},
    )
    conn.execute(
        "INSERT INTO opportunities (id, company_id, signal_id, status, score, fit_notes, decision_trace) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            opp.id,
            opp.company_id,
            opp.signal_id,
            opp.status.value,
            opp.score,
            json.dumps(opp.fit_notes),
            json.dumps(opp.decision_trace),
        ),
    )
    conn.commit()
    return opp


def generate_signals(conn: sqlite3.Connection, rng: Any | None = None) -> list[Signal]:
    """Generate synthetic signals from the seeded company data.

    Each company has a deterministic probability of generating a signal
    based on its tags and stage. Called by the heartbeat scheduler.
    """
    import random

    _rng = rng if rng is not None else random.Random()
    rows = conn.execute("SELECT id, name, segment, stage, employees, tags FROM companies").fetchall()
    signals: list[Signal] = []

    for row in rows:
        tags = json.loads(row["tags"])
        # Companies with "funding" or "seed-funded" tags are more likely to emit FUNDING signals
        if "funding" in tags or "seed-funded" in tags:
            if _rng.random() < SIGNAL_PROB_FUNDING:
                sig = Signal(
                    id=f"sig-{uuid.uuid4().hex[:12]}",
                    company_id=row["id"],
                    type=SignalType.FUNDING,
                    payload={"amount": _rng.choice(["$2M seed", "$5M Series A", "$10M Series B"]),
                             "source": "synthetic_feed"},
                    detected_at=datetime.now(UTC),
                )
                signals.append(sig)
        if "v2" in tags or "expansion" in tags:
            if _rng.random() < SIGNAL_PROB_PRODUCT:
                sig = Signal(
                    id=f"sig-{uuid.uuid4().hex[:12]}",
                    company_id=row["id"],
                    type=SignalType.PRODUCT,
                    payload={"product": "v2 launch", "source": "synthetic_feed"},
                    detected_at=datetime.now(UTC),
                )
                signals.append(sig)
        if row["employees"] > HIRING_EMPLOYEE_THRESHOLD and _rng.random() < SIGNAL_PROB_HIRING:
            sig = Signal(
                id=f"sig-{uuid.uuid4().hex[:12]}",
                company_id=row["id"],
                type=SignalType.HIRING,
                payload={"role": _rng.choice(["VP Sales", "Head of Growth", "Engineering Lead"]),
                         "source": "synthetic_feed"},
                detected_at=datetime.now(UTC),
            )
            signals.append(sig)

    return signals
