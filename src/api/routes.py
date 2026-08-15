"""API routes: approval queue, decision endpoints, control (PLAN.md block 4, D3).

Routes:
    GET  /api/v1/queue             — approval queue (actions with status PROPOSED)
    GET  /api/v1/decisions/{id}    — decision card for an action
    POST /api/v1/decisions/{id}/approve  — approve an action
    POST /api/v1/decisions/{id}/reject   — reject with reason
    POST /api/v1/decisions/{id}/edit     — edit and approve
    POST /api/v1/control/pause     — suspend new actions
    POST /api/v1/control/stop      — halt everything
    POST /api/v1/control/resume    — resume operations
    GET  /api/v1/activity          — activity trail (filterable)
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..domain.enums import ActionStatus, Actor, Mode, OpportunityStatus, OutcomeResult
from ..domain.models import Outcome
from .auth import require_api_key
from ..engine.permission import (
    AUTOPILOT_DEFAULT_SCOPE,
    get_control_status,
    log_activity,
    set_control_status,
)
from ..engine.propose import build_decision_card
from ..engine.learn import apply_feedback
from ..store.db import connect

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


# --- Request models ----------------------------------------------------------

class RejectRequest(BaseModel):
    reason: str
    note: str = ""


class ApproveRequest(BaseModel):
    note: str = ""


class EditRequest(BaseModel):
    subject: str = ""
    body: str = ""
    note: str = ""


class DecisionMutationResponse(BaseModel):
    status: str
    action_id: str
    reason: str | None = None


# --- Approval queue ----------------------------------------------------------

@router.get("/queue")
def get_queue() -> list[dict]:
    """Return all actions awaiting approval (status=PROPOSED)."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT a.*, c.name AS contact_name, c.title AS contact_title, "
            "co.name AS company_name, co.segment "
            "FROM actions a "
            "JOIN contacts c ON c.id = a.contact_id "
            "JOIN companies co ON co.id = c.company_id "
            "WHERE a.status = ? ORDER BY a.created_at",
            (ActionStatus.PROPOSED.value,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["decision_trace"] = json.loads(d.get("decision_trace", "{}"))
            d["guardrail_blocks"] = json.loads(d.get("guardrail_blocks", "[]"))
            result.append(d)
        return result
    finally:
        conn.close()


@router.get("/decisions/{action_id}")
def get_decision_card(action_id: str) -> dict:
    """Return the full decision card for an action."""
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Action not found")
        card = build_decision_card(conn, dict(row))
        return card.model_dump()
    finally:
        conn.close()


# --- Decision endpoints ------------------------------------------------------

@router.post("/decisions/{action_id}/approve")
def approve_action(action_id: str, req: ApproveRequest | None = None) -> DecisionMutationResponse:
    """Approve an action for execution."""
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Action not found")
        if row["status"] != ActionStatus.PROPOSED.value:
            raise HTTPException(status_code=400, detail=f"Action status is {row['status']}, expected PROPOSED")

        conn.execute(
            "UPDATE actions SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (ActionStatus.APPROVED.value, action_id),
        )
        # Update opportunity status
        conn.execute(
            "UPDATE opportunities SET status = ? WHERE id = ?",
            (OpportunityStatus.APPROVED.value, row["opportunity_id"]),
        )
        note = req.note if req else ""
        log_activity(conn, Actor.USER.value, action_id, "approve", status=ActionStatus.APPROVED.value, detail=note)
        conn.commit()
        return DecisionMutationResponse(status="approved", action_id=action_id)
    finally:
        conn.close()


@router.post("/decisions/{action_id}/reject")
def reject_action(action_id: str, req: RejectRequest) -> DecisionMutationResponse:
    """Reject an action with a reason."""
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Action not found")
        if row["status"] != ActionStatus.PROPOSED.value:
            raise HTTPException(status_code=400, detail=f"Action status is {row['status']}, expected PROPOSED")

        conn.execute(
            "UPDATE actions SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (ActionStatus.REJECTED.value, action_id),
        )
        conn.execute(
            "UPDATE opportunities SET status = ? WHERE id = ?",
            (OpportunityStatus.REJECTED.value, row["opportunity_id"]),
        )
        log_activity(
            conn, Actor.USER.value, action_id, "reject",
            status=ActionStatus.REJECTED.value,
            reason=req.reason,
            detail=req.note,
        )
        apply_feedback(conn, action_id, reason=req.reason)
        conn.commit()
        return DecisionMutationResponse(status="rejected", action_id=action_id, reason=req.reason)
    finally:
        conn.close()


@router.post("/decisions/{action_id}/edit")
def edit_action(action_id: str, req: EditRequest) -> DecisionMutationResponse:
    """Edit an action's message and approve it."""
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Action not found")
        if row["status"] != ActionStatus.PROPOSED.value:
            raise HTTPException(status_code=400, detail=f"Action status is {row['status']}, expected PROPOSED")

        updates = {"status": ActionStatus.EDITED.value}
        if req.subject:
            updates["subject"] = req.subject
        if req.body:
            updates["body"] = req.body

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE actions SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
            (*updates.values(), action_id),
        )
        conn.execute(
            "UPDATE opportunities SET status = ? WHERE id = ?",
            (OpportunityStatus.EDITED.value, row["opportunity_id"]),
        )
        log_activity(
            conn, Actor.USER.value, action_id, "edit",
            status=ActionStatus.EDITED.value,
            detail=req.note or json.dumps({"subject": req.subject, "body": req.body}),
        )
        edits = {}
        if req.subject:
            edits["personalization_count"] = len(req.subject.split())
        if req.body:
            edits["tone"] = "warmer" if any(w in req.body.lower() for w in ["hi", "hello", "thanks"]) else "cooler"
        apply_feedback(conn, action_id, edits=edits if edits else None)
        conn.commit()
        return DecisionMutationResponse(status="edited", action_id=action_id)
    finally:
        conn.close()


# --- Control endpoints -------------------------------------------------------

@router.post("/control/pause")
def pause() -> dict:
    """Suspend new actions (keep UI running)."""
    conn = connect()
    try:
        status = set_control_status("paused")
        log_activity(conn, Actor.USER.value, None, "control", status="paused", detail="Kill switch: pause")
        return {"status": status}
    finally:
        conn.close()


@router.post("/control/stop")
def stop() -> dict:
    """Halt everything including heartbeat."""
    conn = connect()
    try:
        status = set_control_status("stopped")
        log_activity(conn, Actor.USER.value, None, "control", status="stopped", detail="Kill switch: stop")
        return {"status": status}
    finally:
        conn.close()


@router.post("/control/resume")
def resume() -> dict:
    """Resume operations."""
    conn = connect()
    try:
        status = set_control_status("running")
        log_activity(conn, Actor.USER.value, None, "control", status="running", detail="Kill switch: resume")
        return {"status": status}
    finally:
        conn.close()


@router.get("/control/status")
def control_status() -> dict:
    """Return current control status."""
    return {"status": get_control_status()}


# --- Activity trail ----------------------------------------------------------

@router.get("/activity")
def get_activity(limit: int = 50, offset: int = 0, actor: str = "", status: str = "", event: str = "") -> list[dict]:
    """Return the activity trail (most recent first), filterable by actor, status, event."""
    conn = connect()
    try:
        conditions = []
        params: list[Any] = []
        if actor:
            conditions.append("actor = ?")
            params.append(actor)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if event:
            conditions.append("event = ?")
            params.append(event)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = conn.execute(
            f"SELECT * FROM activity {where} ORDER BY at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --- Leaderboard (PLAN.md §7.3 G3) -------------------------------------------

@router.get("/leaderboard")
def get_leaderboard() -> list[dict]:
    """Return variant stats table — the visual 'learning happened' proof."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT variant_id, segment, template, channel, timing, tone, "
            "personalization_depth, stats FROM experiments ORDER BY variant_id"
        ).fetchall()
        result = []
        for r in rows:
            stats = json.loads(r["stats"])
            sent = stats.get("sent", 0)
            replies = stats.get("replies", 0)
            meetings = stats.get("meetings", 0)
            result.append({
                "variant_id": r["variant_id"],
                "segment": r["segment"],
                "template": r["template"],
                "channel": r["channel"],
                "timing": r["timing"],
                "tone": r["tone"],
                "personalization_depth": r["personalization_depth"],
                "sent": sent,
                "replies": replies,
                "meetings": meetings,
                "reply_rate": round(replies / sent, 3) if sent > 0 else 0.0,
                "meeting_rate": round(meetings / sent, 3) if sent > 0 else 0.0,
            })
        return result
    finally:
        conn.close()


@router.get("/experiments/analysis")
def get_experiments_analysis(min_samples: int = 5) -> list[dict]:
    """Per-variant Beta credible intervals + probability of beating the best other."""
    from src.engine.experiments import analysis
    conn = connect()
    try:
        return analysis(conn, min_samples=min_samples)
    finally:
        conn.close()


@router.get("/experiments/regret")
def get_experiments_regret(cycle_size: int = 5) -> list[dict]:
    """Per-cycle regret series — declines as the loop learns."""
    from src.engine.experiments import regret_by_cycle
    conn = connect()
    try:
        return regret_by_cycle(conn, cycle_size=cycle_size)
    finally:
        conn.close()


@router.get("/briefing")
def get_briefing(period: str = "week") -> dict:
    """Evidence-backed loop digest: what ran, what changed and why, what needs attention."""
    from src.engine.briefing import briefing
    conn = connect()
    try:
        return briefing(conn, period=period)
    finally:
        conn.close()


@router.get("/audit/export")
def get_audit_export() -> dict:
    """Complete, replayable audit trail (actions + traces + outcomes + activity)."""
    from datetime import UTC, datetime
    from src.engine.audit import audit_export
    conn = connect()
    try:
        export = audit_export(conn)
        export["exported_at"] = datetime.now(UTC).isoformat()
        return export
    finally:
        conn.close()


@router.get("/audit/explain/{action_id}")
def get_audit_explain(action_id: str) -> dict:
    """Full trace: raw decision_trace + template + policy snapshot for an action."""
    from src.engine.audit import explain_action
    conn = connect()
    try:
        result = explain_action(conn, action_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Action not found: {action_id}")
        return result
    finally:
        conn.close()


@router.get("/audit/pii")
def get_audit_pii() -> dict:
    """Scan drafted bodies/subjects against PII patterns + banned phrases."""
    from src.engine.audit import pii_report
    conn = connect()
    try:
        return pii_report(conn)
    finally:
        conn.close()


@router.get("/pipeline")
def get_pipeline() -> list[dict]:
    """Revenue funnel: QUALIFIED → PROPOSED → SENT → OUTCOME → WON with ARR."""
    from src.engine.revenue import pipeline
    conn = connect()
    try:
        return pipeline(conn)
    finally:
        conn.close()


@router.get("/attribution")
def get_attribution() -> dict:
    """ARR attributed per variant, channel, segment, action type, policy version."""
    from src.engine.revenue import attribution
    conn = connect()
    try:
        return attribution(conn)
    finally:
        conn.close()


@router.get("/sequences")
def get_sequences() -> list[dict]:
    """List seeded multi-touch sequences with their steps and Thompson stats."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT s.sequence_id, s.name, s.segment, s.max_steps, s.stats, "
            "GROUP_CONCAT(s2.action_type || ':' || s2.channel || ':' || s2.delay_days, ' -> ') AS steps "
            "FROM sequences s LEFT JOIN sequence_steps s2 ON s2.sequence_id = s.sequence_id "
            "GROUP BY s.sequence_id ORDER BY s.sequence_id"
        ).fetchall()
        result = []
        for r in rows:
            stats = json.loads(r["stats"])
            result.append({
                "sequence_id": r["sequence_id"],
                "name": r["name"],
                "segment": r["segment"],
                "max_steps": r["max_steps"],
                "stats": stats,
                "steps": r["steps"] or "",
            })
        return result
    finally:
        conn.close()


# --- Outcomes ----------------------------------------------------------------

@router.get("/outcomes")
def get_outcomes(limit: int = 50) -> list[dict]:
    """Return recorded outcomes (most recent first)."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM outcomes ORDER BY at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --- Companies ---------------------------------------------------------------

@router.get("/companies")
def get_companies() -> list[dict]:
    """Return all companies."""
    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM companies ORDER BY name").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d["tags"])
            result.append(d)
        return result
    finally:
        conn.close()


# --- Contacts ----------------------------------------------------------------

@router.get("/contacts")
def get_contacts(company_id: str | None = None) -> list[dict]:
    """Return contacts, optionally filtered by company_id."""
    conn = connect()
    try:
        if company_id:
            rows = conn.execute(
                "SELECT * FROM contacts WHERE company_id = ? ORDER BY name", (company_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM contacts ORDER BY name").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --- Variants (experiments table) --------------------------------------------

class VariantCreate(BaseModel):
    variant_id: str
    segment: str
    template: str
    channel: str
    timing: str
    tone: str
    personalization_depth: int = 1


class VariantUpdate(BaseModel):
    template: str | None = None
    channel: str | None = None
    timing: str | None = None
    tone: str | None = None
    personalization_depth: int | None = None


@router.get("/variants")
def get_variants() -> list[dict]:
    """Return all playbook variants."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT variant_id, segment, template, channel, timing, tone, "
            "personalization_depth, stats FROM experiments ORDER BY variant_id"
        ).fetchall()
        result = []
        for r in rows:
            stats = json.loads(r["stats"])
            result.append({
                "id": r["variant_id"],
                "name": r["variant_id"],
                "template": r["template"],
                "channel": r["channel"],
                "timing_slot": r["timing"],
                "tone_profile": r["tone"],
                "personalization_depth": r["personalization_depth"],
                "segment": r["segment"],
                "stats": stats,
            })
        return result
    finally:
        conn.close()


@router.post("/variants")
def create_variant(req: VariantCreate) -> dict:
    """Create a new playbook variant."""
    conn = connect()
    try:
        existing = conn.execute(
            "SELECT variant_id FROM experiments WHERE variant_id = ?", (req.variant_id,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Variant already exists")
        conn.execute(
            "INSERT INTO experiments (variant_id, segment, template, channel, timing, tone, "
            "personalization_depth, stats) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (req.variant_id, req.segment, req.template, req.channel, req.timing,
             req.tone, req.personalization_depth, json.dumps({"sent": 0, "replies": 0, "meetings": 0})),
        )
        conn.commit()
        return {
            "id": req.variant_id, "name": req.variant_id,
            "template": req.template, "channel": req.channel,
            "timing_slot": req.timing, "tone_profile": req.tone,
            "personalization_depth": req.personalization_depth,
            "segment": req.segment, "stats": {"sent": 0, "replies": 0, "meetings": 0},
        }
    finally:
        conn.close()


@router.patch("/variants/{variant_id}")
def update_variant(variant_id: str, req: VariantUpdate) -> dict:
    """Update a playbook variant."""
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM experiments WHERE variant_id = ?", (variant_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Variant not found")
        updates = {}
        if req.template is not None:
            updates["template"] = req.template
        if req.channel is not None:
            updates["channel"] = req.channel
        if req.timing is not None:
            updates["timing"] = req.timing
        if req.tone is not None:
            updates["tone"] = req.tone
        if req.personalization_depth is not None:
            updates["personalization_depth"] = req.personalization_depth
        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE experiments SET {set_clause} WHERE variant_id = ?",
                         (*updates.values(), variant_id))
            conn.commit()
        stats = json.loads(row["stats"])
        return {
            "id": variant_id, "name": variant_id,
            "template": updates.get("template", row["template"]),
            "channel": updates.get("channel", row["channel"]),
            "timing_slot": updates.get("timing", row["timing"]),
            "tone_profile": updates.get("tone", row["tone"]),
            "personalization_depth": updates.get("personalization_depth", row["personalization_depth"]),
            "segment": row["segment"], "stats": stats,
        }
    finally:
        conn.close()


# --- Policy ------------------------------------------------------------------

class PolicyUpdate(BaseModel):
    brevity: float | None = None
    tone_assertiveness: float | None = None
    personalization_depth: int | None = None
    banned_phrases: list[str] | None = None


@router.get("/policy")
def get_policy() -> dict:
    """Return the current (latest) policy."""
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM policies ORDER BY version DESC LIMIT 1").fetchone()
        if not row:
            return {"version": 1, "brevity": 0.5, "tone_assertiveness": 0.5,
                    "personalization_depth": 1, "banned_phrases": []}
        data = json.loads(row["policy"])
        data["version"] = row["version"]
        return data
    finally:
        conn.close()


@router.patch("/policy")
def update_policy(req: PolicyUpdate) -> dict:
    """Create a new policy version with updated fields."""
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM policies ORDER BY version DESC LIMIT 1").fetchone()
        current = json.loads(row["policy"]) if row else {
            "brevity": 0.5, "tone_assertiveness": 0.5, "personalization_depth": 1
        }
        if req.brevity is not None:
            current["brevity"] = req.brevity
        if req.tone_assertiveness is not None:
            current["tone_assertiveness"] = req.tone_assertiveness
        if req.personalization_depth is not None:
            current["personalization_depth"] = req.personalization_depth
        if req.banned_phrases is not None:
            current["banned_phrases"] = req.banned_phrases

        new_version = (row["version"] + 1) if row else 1
        conn.execute(
            "INSERT INTO policies (version, policy, source) VALUES (?, ?, ?)",
            (new_version, json.dumps(current), "api_update"),
        )
        conn.commit()
        log_activity(conn, Actor.USER.value, None, "policy_update",
                     policy_version=new_version, detail=json.dumps(current))
        current["version"] = new_version
        return current
    finally:
        conn.close()


@router.post("/policy/rollback/{version}")
def rollback_policy(version: int) -> dict:
    """Rollback to a previous policy version."""
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM policies WHERE version = ?", (version,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Policy version {version} not found")
        data = json.loads(row["policy"])
        current_row = conn.execute("SELECT MAX(version) AS v FROM policies").fetchone()
        new_version = (current_row["v"] + 1) if current_row and current_row["v"] else 1
        conn.execute(
            "INSERT INTO policies (version, policy, source) VALUES (?, ?, ?)",
            (new_version, json.dumps(data), f"rollback_from_{version}"),
        )
        conn.commit()
        log_activity(conn, Actor.USER.value, None, "policy_rollback",
                     policy_version=new_version, detail=f"Rolled back to version {version}")
        data["version"] = new_version
        return data
    finally:
        conn.close()


# --- Warm Graph --------------------------------------------------------------

@router.get("/warm-graph")
def get_warm_graph() -> list[dict]:
    """Return all warm edges."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT we.id, we.contact_a AS source_contact_id, we.contact_b AS target_contact_id, "
            "we.strength, we.direction, we.last_interaction, we.source "
            "FROM warm_edges we ORDER BY we.strength DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


class WarmEdgeUpdate(BaseModel):
    strength: float | None = None
    direction: str | None = None
    last_interaction: str | None = None


@router.patch("/warm-graph/{edge_id}")
def update_warm_edge(edge_id: int, req: WarmEdgeUpdate) -> dict:
    """Update a warm edge."""
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM warm_edges WHERE id = ?", (edge_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Warm edge not found")
        updates = {}
        if req.strength is not None:
            updates["strength"] = req.strength
        if req.direction is not None:
            updates["direction"] = req.direction
        if req.last_interaction is not None:
            updates["last_interaction"] = req.last_interaction
        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE warm_edges SET {set_clause} WHERE id = ?",
                         (*updates.values(), edge_id))
            conn.commit()
        updated = conn.execute("SELECT * FROM warm_edges WHERE id = ?", (edge_id,)).fetchone()
        return dict(updated)
    finally:
        conn.close()


# --- Outcomes (POST) ---------------------------------------------------------

class OutcomeCreate(BaseModel):
    action_id: str
    result: str
    detail: str = ""


# --- Enriched product resources --------------------------------------------

def _json_value(value: str | None, default: object) -> object:
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return default


def _opportunity_payload(conn, row, include_detail: bool = False) -> dict:
    """Build the stable opportunity shape consumed by the operator console."""
    contact = conn.execute(
        "SELECT c.id, c.name, c.title, c.email, c.linkedin, c.warmth "
        "FROM contacts c WHERE c.id = COALESCE(("
        "SELECT a.contact_id FROM actions a WHERE a.opportunity_id = ? "
        "ORDER BY a.created_at DESC LIMIT 1), ("
        "SELECT c2.id FROM contacts c2 WHERE c2.company_id = ? "
        "ORDER BY c2.name LIMIT 1))",
        (row["id"], row["company_id"]),
    ).fetchone()
    action = conn.execute(
        "SELECT * FROM actions WHERE opportunity_id = ? ORDER BY created_at DESC LIMIT 1",
        (row["id"],),
    ).fetchone()
    signal_payload = _json_value(row["signal_payload"], {})
    result = {
        "id": row["id"],
        "company_id": row["company_id"],
        "company": {
            "id": row["company_id"],
            "name": row["company_name"],
            "segment": row["segment"],
            "stage": row["stage"],
            "employees": row["employees"],
            "tags": _json_value(row["tags"], []),
        },
        "contact": dict(contact) if contact else None,
        "signal": {
            "id": row["signal_id"],
            "type": row["signal_type"],
            "payload": signal_payload,
            "detected_at": row["detected_at"],
        },
        "status": row["status"],
        "score": row["score"],
        "fit_notes": _json_value(row["fit_notes"], []),
        "created_at": row["created_at"],
        "pipeline_stage": row["pipeline_stage"],
        "arr": row["arr"],
        "current_action": dict(action) if action else None,
    }
    if not include_detail:
        return result

    signals = conn.execute(
        "SELECT id, type, payload, detected_at FROM signals "
        "WHERE company_id = ? ORDER BY detected_at DESC",
        (row["company_id"],),
    ).fetchall()
    previous_actions = conn.execute(
        "SELECT id, action_type, channel, status, subject, created_at, updated_at "
        "FROM actions WHERE opportunity_id = ? ORDER BY created_at DESC",
        (row["id"],),
    ).fetchall()
    edges = []
    if contact:
        edges = conn.execute(
            "SELECT we.id, we.contact_a, we.contact_b, we.strength, we.direction, "
            "we.last_interaction, we.source, ca.name AS contact_a_name, "
            "cb.name AS contact_b_name FROM warm_edges we "
            "JOIN contacts ca ON ca.id = we.contact_a JOIN contacts cb ON cb.id = we.contact_b "
            "WHERE we.contact_a = ? OR we.contact_b = ? ORDER BY we.strength DESC",
            (contact["id"], contact["id"]),
        ).fetchall()
    result["signal_timeline"] = [
        {"id": signal["id"], "type": signal["type"], "payload": _json_value(signal["payload"], {}), "detected_at": signal["detected_at"]}
        for signal in signals
    ]
    result["previous_actions"] = [dict(item) for item in previous_actions]
    result["relationship_edges"] = [dict(edge) for edge in edges]
    result["why_now"] = (
        "Fresh signal with a qualified fit and an available relationship path."
        if row["score"] >= 0.6 else "Signal remains below the current qualification threshold."
    )
    result["what_would_change_this"] = [
        "New negative outcome or unsubscribe",
        "Signal becomes stale beyond the configured window",
        "A guardrail or contact frequency cap blocks the action",
    ]
    return result


@router.get("/opportunities")
def get_opportunities(
    q: str = Query("", max_length=200),
    status: str = "",
    signal_type: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """Return enriched, filterable opportunities for the operator queue."""
    conn = connect()
    try:
        conditions = []
        params: list[Any] = []
        if q:
            conditions.append("(co.name LIKE ? OR ct.name LIKE ? OR s.type LIKE ? OR s.payload LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"])
        if status:
            conditions.append("o.status = ?")
            params.append(status.upper())
        if signal_type:
            conditions.append("s.type = ?")
            params.append(signal_type.upper())
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        base_query = (
            "SELECT o.*, co.name AS company_name, co.segment, co.stage, co.employees, co.tags, "
            "s.type AS signal_type, s.payload AS signal_payload, s.detected_at "
            "FROM opportunities o JOIN companies co ON co.id = o.company_id "
            "JOIN signals s ON s.id = o.signal_id "
            "LEFT JOIN contacts ct ON ct.company_id = o.company_id "
            f"{where} GROUP BY o.id ORDER BY o.score DESC, s.detected_at DESC LIMIT ? OFFSET ?"
        )
        rows = conn.execute(base_query, (*params, limit, offset)).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM opportunities o "
            "JOIN companies co ON co.id = o.company_id "
            "JOIN signals s ON s.id = o.signal_id "
            "LEFT JOIN contacts ct ON ct.company_id = o.company_id "
            f"{where}",
            params,
        ).fetchone()["n"]
        return {"items": [_opportunity_payload(conn, row) for row in rows], "total": total, "limit": limit, "offset": offset}
    finally:
        conn.close()


@router.get("/opportunities/{opportunity_id}")
def get_opportunity(opportunity_id: str) -> dict:
    """Return one opportunity with evidence, timeline, path, and recommendation."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT o.*, co.name AS company_name, co.segment, co.stage, co.employees, co.tags, "
            "s.type AS signal_type, s.payload AS signal_payload, s.detected_at "
            "FROM opportunities o JOIN companies co ON co.id = o.company_id "
            "JOIN signals s ON s.id = o.signal_id WHERE o.id = ?",
            (opportunity_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Opportunity not found: {opportunity_id}")
        return _opportunity_payload(conn, row, include_detail=True)
    finally:
        conn.close()


@router.get("/actions/{action_id}/timeline")
def get_action_timeline(action_id: str) -> dict:
    """Return the persisted nine-stage trace for an action."""
    conn = connect()
    try:
        action = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
        if not action:
            raise HTTPException(status_code=404, detail=f"Action not found: {action_id}")
        activity = conn.execute(
            "SELECT at, actor, event, status, outcome, reason, policy_version, detail "
            "FROM activity WHERE action_id = ? ORDER BY at",
            (action_id,),
        ).fetchall()
        outcome = conn.execute("SELECT * FROM outcomes WHERE action_id = ? ORDER BY at DESC LIMIT 1", (action_id,)).fetchone()
        stages = [
            ("Signal", "Signal attached to opportunity"),
            ("Qualify", "Opportunity qualification and evidence recorded"),
            ("Select", f"Variant {action['variant_id']} selected at {action['confidence']:.0%} confidence"),
            ("Draft", f"{len((action['body'] or '').split())} words generated under policy v{action['policy_version']}"),
            ("Guardrails", "Guardrail checks evaluated before execution"),
            ("Decision", f"Human or autopilot decision: {action['status']}"),
            ("Execute", f"{action['channel']} execution path"),
            ("Outcome", outcome["result"] if outcome else "Pending"),
            ("Learn", "Outcome and feedback available for policy learning" if outcome else "Awaiting outcome"),
        ]
        return {
            "action_id": action_id,
            "status": action["status"],
            "policy_version": action["policy_version"],
            "stages": [
                {"index": index + 1, "name": name, "detail": detail, "completed": index < 7 or bool(outcome)}
                for index, (name, detail) in enumerate(stages)
            ],
            "activity": [dict(item) for item in activity],
            "outcome": dict(outcome) if outcome else None,
        }
    finally:
        conn.close()


@router.get("/learning/changes")
def get_learning_changes() -> dict:
    """Return behavior changes derived from stored policies, feedback, and outcomes."""
    conn = connect()
    try:
        policies = conn.execute("SELECT version, policy, created_at, source FROM policies ORDER BY version").fetchall()
        feedback = conn.execute(
            "SELECT at, action_id, event, reason, detail, policy_version FROM activity "
            "WHERE event IN ('reject', 'edit', 'policy_update', 'policy_rollback') ORDER BY at DESC LIMIT 100"
        ).fetchall()
        outcomes = conn.execute(
            "SELECT o.at, o.action_id, o.result, o.detail, a.variant_id, a.channel "
            "FROM outcomes o JOIN actions a ON a.id = o.action_id ORDER BY o.at DESC LIMIT 100"
        ).fetchall()
        return {
            "active_policy_version": policies[-1]["version"] if policies else 0,
            "policies": [{"version": row["version"], "policy": _json_value(row["policy"], {}), "created_at": row["created_at"], "source": row["source"]} for row in policies],
            "feedback": [dict(row) for row in feedback],
            "outcomes": [dict(row) for row in outcomes],
        }
    finally:
        conn.close()


@router.get("/policy/history")
def get_policy_history() -> list[dict]:
    """Return policy versions with a simple field-level diff from the prior version."""
    conn = connect()
    try:
        rows = conn.execute("SELECT version, policy, created_at, source FROM policies ORDER BY version").fetchall()
        history = []
        previous: dict = {}
        for row in rows:
            current = _json_value(row["policy"], {})
            diff = {
                key: {"before": previous.get(key), "after": value}
                for key, value in current.items()
                if previous.get(key) != value
            }
            history.append({"version": row["version"], "policy": current, "created_at": row["created_at"], "source": row["source"], "diff": diff})
            previous = current
        return history
    finally:
        conn.close()


@router.post("/outcomes")
def record_outcome(req: OutcomeCreate) -> dict:
    """Record an outcome for an action."""
    conn = connect()
    try:
        from datetime import UTC, datetime
        from src.engine.observe import record_outcome as observe_record
        outcome = Outcome(
            action_id=req.action_id,
            result=OutcomeResult(req.result),
            detail=req.detail,
            at=datetime.now(UTC),
        )
        observe_record(conn, outcome)
        log_activity(conn, Actor.AGENT.value, req.action_id, "outcome",
                     outcome=req.result, detail=req.detail)
        return {"id": f"out-{req.action_id}", "action_id": req.action_id,
                "result": req.result, "detail": req.detail}
    finally:
        conn.close()


# --- Control: mode + scope ---------------------------------------------------

class ModeRequest(BaseModel):
    mode: str  # "PROPOSE" or "AUTOPILOT"


class ScopeRequest(BaseModel):
    enabled: bool | None = None
    allowed_segments: list[str] | None = None
    allowed_channels: list[str] | None = None
    allowed_timing: list[str] | None = None
    max_sends_per_day: int | None = None
    max_cost_units_per_action: int | None = None


class ApplicationSettingsUpdate(BaseModel):
    theme: Literal["system", "light", "dark"] | None = None
    density: Literal["comfortable", "compact"] | None = None
    date_format: Literal["locale", "iso"] | None = None
    time_format: Literal["12h", "24h"] | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    refresh_interval_seconds: int | None = Field(default=None, ge=5, le=3600)
    default_landing_page: Literal["today", "opportunities", "approvals", "activity"] | None = None
    default_opportunity_sort: Literal["score", "recency", "value"] | None = None
    feature_flags: dict[str, bool] | None = None


class WorkspaceSettingsUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    default_currency: str | None = Field(default=None, min_length=3, max_length=3)
    default_segment: str | None = Field(default=None, max_length=120)


def _get_scope() -> dict:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT value FROM memory_kv WHERE key = 'autopilot_scope'"
        ).fetchone()
        if row:
            return json.loads(row["value"])
    finally:
        conn.close()
    return dict(AUTOPILOT_DEFAULT_SCOPE)


_APPLICATION_SETTINGS_DEFAULTS = {
    "theme": "system",
    "density": "comfortable",
    "date_format": "locale",
    "time_format": "12h",
    "currency": "USD",
    "refresh_interval_seconds": 10,
    "default_landing_page": "today",
    "default_opportunity_sort": "score",
    "feature_flags": {},
}

_WORKSPACE_SETTINGS_DEFAULTS = {
    "name": "",
    "timezone": "UTC",
    "default_currency": "USD",
    "default_segment": "",
}


def _read_settings(conn, key: str, defaults: dict) -> dict:
    row = conn.execute("SELECT value FROM memory_kv WHERE key = ?", (key,)).fetchone()
    if not row:
        return dict(defaults)
    try:
        value = json.loads(row["value"])
    except (TypeError, ValueError):
        return dict(defaults)
    return {**defaults, **value} if isinstance(value, dict) else dict(defaults)


def _write_settings(conn, key: str, namespace: str, settings: dict, event: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO memory_kv (key, namespace, value, updated_at) "
        "VALUES (?, ?, ?, datetime('now'))",
        (key, namespace, json.dumps(settings)),
    )
    log_activity(
        conn,
        Actor.USER.value,
        None,
        event,
        status="UPDATED",
        detail=json.dumps({"resource": key, "fields": sorted(settings)}),
    )


@router.get("/settings/application")
def get_application_settings() -> dict:
    """Return persisted application/UI preferences."""
    conn = connect()
    try:
        return {"settings": _read_settings(conn, "settings.application", _APPLICATION_SETTINGS_DEFAULTS)}
    finally:
        conn.close()


@router.patch("/settings/application")
def update_application_settings(req: ApplicationSettingsUpdate) -> dict:
    """Validate and persist application/UI preferences without touching domain data."""
    conn = connect()
    try:
        settings = _read_settings(conn, "settings.application", _APPLICATION_SETTINGS_DEFAULTS)
        settings.update(req.model_dump(exclude_none=True))
        _write_settings(conn, "settings.application", "settings.application", settings, "application_settings_update")
        conn.commit()
        return {"settings": settings}
    finally:
        conn.close()


@router.post("/settings/application/reset")
def reset_application_settings() -> dict:
    """Reset only application preferences; domain data and credentials are untouched."""
    conn = connect()
    try:
        settings = dict(_APPLICATION_SETTINGS_DEFAULTS)
        _write_settings(conn, "settings.application", "settings.application", settings, "application_settings_reset")
        conn.commit()
        return {"settings": settings, "reset": True}
    finally:
        conn.close()


@router.get("/settings/workspace")
def get_workspace_settings() -> dict:
    """Return persisted workspace preferences."""
    conn = connect()
    try:
        return {"settings": _read_settings(conn, "settings.workspace", _WORKSPACE_SETTINGS_DEFAULTS)}
    finally:
        conn.close()


@router.patch("/settings/workspace")
def update_workspace_settings(req: WorkspaceSettingsUpdate) -> dict:
    """Validate and persist workspace preferences."""
    conn = connect()
    try:
        settings = _read_settings(conn, "settings.workspace", _WORKSPACE_SETTINGS_DEFAULTS)
        settings.update(req.model_dump(exclude_none=True))
        _write_settings(conn, "settings.workspace", "settings.workspace", settings, "workspace_settings_update")
        conn.commit()
        return {"settings": settings}
    finally:
        conn.close()


def _save_scope(scope: dict) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO memory_kv (key, namespace, value, updated_at) "
            "VALUES ('autopilot_scope', 'control', ?, datetime('now'))",
            (json.dumps(scope),),
        )
        conn.commit()
    finally:
        conn.close()


@router.post("/control/mode")
def set_mode(req: ModeRequest) -> dict:
    """Set the operating mode (PROPOSE or AUTOPILOT)."""
    mode = req.mode.upper()
    if mode not in ("PROPOSE", "AUTOPILOT"):
        raise HTTPException(status_code=400, detail="Mode must be PROPOSE or AUTOPILOT")
    scope = _get_scope()
    scope["enabled"] = mode == "AUTOPILOT"
    _save_scope(scope)
    conn = connect()
    try:
        log_activity(conn, Actor.USER.value, None, "control",
                     detail=f"Mode set to {mode}")
        conn.commit()
    finally:
        conn.close()
    return {"mode": mode, "scope": scope}


@router.get("/control/scope")
def get_scope() -> dict:
    """Return the persisted autopilot scope for the Settings workspace."""
    return {"scope": _get_scope()}


@router.post("/control/scope")
def set_scope(req: ScopeRequest) -> dict:
    """Update autopilot scope configuration."""
    scope = _get_scope()
    if req.enabled is not None:
        scope["enabled"] = req.enabled
    if req.allowed_segments is not None:
        scope["allowed_segments"] = req.allowed_segments
    if req.allowed_channels is not None:
        scope["allowed_channels"] = req.allowed_channels
    if req.allowed_timing is not None:
        scope["allowed_timing"] = req.allowed_timing
    if req.max_sends_per_day is not None:
        scope["max_sends_per_day"] = req.max_sends_per_day
    if req.max_cost_units_per_action is not None:
        scope["max_cost_units_per_action"] = req.max_cost_units_per_action
    _save_scope(scope)
    conn = connect()
    try:
        log_activity(conn, Actor.USER.value, None, "control",
                     detail=f"Scope updated: {json.dumps(scope)}")
        conn.commit()
    finally:
        conn.close()
    return {"scope": scope}
