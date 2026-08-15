"""FastAPI app for gtm-loop (PLAN.md block 7).

/health + /api/v1/status + approval queue + decisions + control routes.
Heartbeat scheduler for periodic signal scan → NBAM → autopilot pass.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from src.config import HEARTBEAT_INTERVAL_SECONDS, SIMULATION_MODE
from src.api.auth import require_api_key

logger = logging.getLogger("gtm-loop")


# ---------------------------------------------------------------------------
# Heartbeat scheduler (PLAN.md §7.1 G1)
# ---------------------------------------------------------------------------

async def _heartbeat_tick(conn: object = None) -> None:
    """Single heartbeat tick: scan signals, qualify, plan, propose/auto-execute.

    Args:
        conn: Optional DB connection (for testing). When None, opens a fresh connection.
    """
    import json
    import uuid
    from datetime import UTC, datetime

    from src.config import AUTOPILOT_DEFAULT_SCOPE, QUALIFY_THRESHOLD
    from src.engine.permission import get_control_status, evaluate, log_activity
    from src.store.db import connect as db_connect

    if get_control_status() != "running":
        return

    _owns_conn = conn is None
    if _owns_conn:
        conn = db_connect()
    try:
        # 1. Generate synthetic signals and ingest them (deterministic RNG)
        import random as _random
        from src.engine.sense import generate_signals, ingest_signal, scan, qualify, create_opportunity
        _rng = _random.Random(42)  # fixed seed for determinism
        new_signals = generate_signals(conn, rng=_rng)
        for sig in new_signals:
            ingest_signal(conn, sig)

        # 2. Scan and qualify
        signals = scan(conn)
        for sig in signals:
            qual = qualify(conn, sig)
            if qual and qual.score >= QUALIFY_THRESHOLD:
                # Dedupe: skip if opportunity already exists for this signal
                existing_opp = conn.execute(
                    "SELECT id FROM opportunities WHERE signal_id = ?", (sig.id,)
                ).fetchone()
                if not existing_opp:
                    create_opportunity(conn, sig, qual)

        # 2. Plan actions for qualified opportunities
        from src.engine.plan import choose_next_best_action
        from src.engine.generate import TemplateGenerator

        qualified = conn.execute(
            "SELECT o.*, s.type AS signal_type, s.payload AS signal_payload "
            "FROM opportunities o JOIN signals s ON s.id = o.signal_id "
            "WHERE o.status = 'QUALIFIED'"
        ).fetchall()

        gen = TemplateGenerator()
        rng = uuid.uuid4()  # used for determinism; not passed as random seed here

        for opp in qualified:
            # Skip if we already have a proposed/executed action for this opportunity
            existing = conn.execute(
                "SELECT id FROM actions WHERE opportunity_id = ? AND status NOT IN ('BLOCKED', 'FAILED')",
                (opp["id"],),
            ).fetchone()
            if existing:
                continue

            planned = choose_next_best_action(conn, dict(opp))
            if not planned:
                continue

            # Resolve a contact for this company
            contact_row = conn.execute(
                "SELECT * FROM contacts WHERE company_id = ? ORDER BY "
                "CASE warmth WHEN 'replied' THEN 4 WHEN 'met' THEN 3 WHEN 'engaged' THEN 2 ELSE 1 END DESC LIMIT 1",
                (opp["company_id"],),
            ).fetchone()
            if not contact_row:
                continue
            contact = dict(contact_row)

            # Get the variant from DB for the generator
            exp_row = conn.execute(
                "SELECT * FROM experiments WHERE variant_id = ?",
                (planned.variant_id,),
            ).fetchone()
            if not exp_row:
                continue
            from src.domain.models import Experiment
            variant = Experiment(
                variant_id=exp_row["variant_id"],
                segment=exp_row["segment"],
                template=exp_row["template"],
                channel=exp_row["channel"],
                timing=exp_row["timing"],
                tone=exp_row["tone"],
                personalization_depth=exp_row["personalization_depth"],
                stats=json.loads(exp_row["stats"]),
            )

            # Get current policy
            policy_row = conn.execute(
                "SELECT policy FROM policies ORDER BY version DESC LIMIT 1"
            ).fetchone()
            policy = json.loads(policy_row["policy"]) if policy_row else {"brevity": 0.5, "tone_assertiveness": 0.5, "personalization_depth": 1}

            signal_row = conn.execute("SELECT * FROM signals WHERE id = ?", (opp["signal_id"],)).fetchone()
            draft = gen.generate(conn, variant, contact, dict(signal_row), policy)

            # Evaluate permission
            decision = evaluate(
                conn,
                planned.action_type.value,
                contact["id"],
                cost_units=1,
                body=draft.body,
                mode=AUTOPILOT_DEFAULT_SCOPE.get("mode", "PROPOSE"),
                scope=AUTOPILOT_DEFAULT_SCOPE,
                channel=planned.channel.value,
                timing=planned.timing.value,
            )

            action_id = f"act-hb-{uuid.uuid4().hex[:8]}"
            now = datetime.now(UTC).isoformat()

            if not decision.requires_approval:
                # Autopilot: execute immediately
                status = "EXECUTED"
                conn.execute(
                    "INSERT INTO actions (id, opportunity_id, contact_id, action_type, variant_id, "
                    "channel, timing, mode, status, subject, body, cost_units, policy_version, "
                    "segment, expected_effect, confidence, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'AUTOPILOT', 'EXECUTED', ?, ?, 1, 1, ?, ?, ?, ?)",
                    (action_id, opp["id"], contact["id"], planned.action_type.value,
                     planned.variant_id, planned.channel.value, planned.timing.value,
                     draft.subject, draft.body, planned.segment, planned.expected_effect,
                     planned.confidence, now),
                )
                conn.commit()
                log_activity(conn, "heartbeat", action_id, "auto_execute", "EXECUTED",
                             reason="autopilot: within scope, no guardrail blocks",
                             policy_version=1, detail=draft.subject)
            else:
                # Propose mode: insert into queue for human review
                conn.execute(
                    "INSERT INTO actions (id, opportunity_id, contact_id, action_type, variant_id, "
                    "channel, timing, mode, status, subject, body, cost_units, policy_version, "
                    "segment, expected_effect, confidence, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'PROPOSE', 'PROPOSED', ?, ?, 1, 1, ?, ?, ?, ?)",
                    (action_id, opp["id"], contact["id"], planned.action_type.value,
                     planned.variant_id, planned.channel.value, planned.timing.value,
                     draft.subject, draft.body, planned.segment, planned.expected_effect,
                     planned.confidence, now),
                )
                conn.commit()
                log_activity(conn, "heartbeat", action_id, "propose", "PROPOSED",
                             reason="; ".join(decision.reasons),
                             policy_version=1, detail=draft.subject)
    except Exception:
        logger.exception("heartbeat tick failed")
    finally:
        if _owns_conn:
            conn.close()


async def _heartbeat_loop(interval: int) -> None:
    """Background loop running heartbeat ticks."""
    while True:
        await asyncio.sleep(interval)
        await _heartbeat_tick()


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start/stop heartbeat scheduler with the app."""
    if SIMULATION_MODE:
        task = asyncio.create_task(_heartbeat_loop(HEARTBEAT_INTERVAL_SECONDS))
        logger.info("heartbeat started (interval=%ds)", HEARTBEAT_INTERVAL_SECONDS)
    yield
    if SIMULATION_MODE:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="gtm-loop",
    description="Self-improving GTM agent — one closed loop: sense, decide, propose, act, observe, learn.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "simulation_mode": SIMULATION_MODE}


@app.get("/api/v1/status", dependencies=[Depends(require_api_key)])
def status() -> dict:
    from datetime import UTC, datetime
    from src.store.db import get_connection, current_version
    from src.engine.permission import get_control_status

    with get_connection() as conn:
        n_actions = conn.execute("SELECT COUNT(*) AS n FROM actions").fetchone()["n"]
        n_outcomes = conn.execute("SELECT COUNT(*) AS n FROM outcomes").fetchone()["n"]
        schema_version = current_version(conn)
        queue_count = conn.execute(
            "SELECT COUNT(*) AS n FROM actions WHERE status = 'PROPOSED'"
        ).fetchone()["n"]
        active_opps = conn.execute(
            "SELECT COUNT(*) AS n FROM opportunities WHERE status NOT IN ('DISMISSED', 'SKIPPED')"
        ).fetchone()["n"]
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        today_sent = conn.execute(
            "SELECT COUNT(*) AS n FROM actions WHERE status = 'SENT' AND created_at >= ?",
            (today,),
        ).fetchone()["n"]
        today_cost = conn.execute(
            "SELECT COALESCE(SUM(cost_units), 0) AS total FROM actions "
            "WHERE created_at >= ? AND status != 'BLOCKED'",
            (today,),
        ).fetchone()["total"]

    control = get_control_status()
    return {
        "schema_version": schema_version,
        "actions": n_actions,
        "outcomes": n_outcomes,
        "simulation_mode": SIMULATION_MODE,
        "mode": "AUTOPILOT" if control == "running" else "PROPOSE",
        "paused": control == "paused",
        "stopped": control == "stopped",
        "queue_count": queue_count,
        "active_opportunities": active_opps,
        "today_sent": today_sent,
        "today_budget_used": today_cost,
    }


# Mount routes
from src.api.routes import router  # noqa: E402
app.include_router(router)
