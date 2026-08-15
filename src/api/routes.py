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
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

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


class EditRequest(BaseModel):
    subject: str = ""
    body: str = ""
    note: str = ""


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
def approve_action(action_id: str, req: RejectRequest | None = None) -> dict:
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
        if note:
            apply_feedback(conn, action_id, reason=None, edits={"personalization_count": 0})
        conn.commit()
        return {"status": "approved", "action_id": action_id}
    finally:
        conn.close()


@router.post("/decisions/{action_id}/reject")
def reject_action(action_id: str, req: RejectRequest) -> dict:
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
        return {"status": "rejected", "action_id": action_id, "reason": req.reason}
    finally:
        conn.close()


@router.post("/decisions/{action_id}/edit")
def edit_action(action_id: str, req: EditRequest) -> dict:
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
        return {"status": "edited", "action_id": action_id}
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
