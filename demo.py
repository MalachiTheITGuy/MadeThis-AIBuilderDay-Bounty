"""Demo script for gtm-loop (PLAN.md §10).

Runs the full loop: sense → decide → propose → (human decision) → observe → learn.
Fully local, deterministic, no network calls.
"""

from __future__ import annotations

import json
import sys

from seed_data import seed
from src.config import AUTOPILOT_DEFAULT_SCOPE
from src.domain.enums import OutcomeResult
from src.domain.models import Outcome
from src.engine.execute import execute_action
from src.engine.generate import TemplateGenerator
from src.engine.learn import apply_feedback, apply_outcome, rollback_policy
from src.engine.observe import synthesize_outcome
from src.engine.permission import evaluate, get_control_status, set_control_status
from src.engine.plan import choose_next_best_action as plan_action
from src.engine.propose import build_decision_card
from src.store.db import connect


def _print_header(scene: str, title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  SCENE {scene}: {title}")
    print(f"{'='*60}\n")


def _print_card(card) -> None:
    print(f"  Action: {card.action_type} via {card.channel}")
    print(f"  Target: {card.target}")
    print(f"  Why: {'; '.join(card.why[:3])}")
    print(f"  Guardrails: {', '.join(card.guardrails) if card.guardrails else 'all pass'}")
    print(f"  Expected: {card.expected_effect}")


def run_demo() -> None:
    db = connect()
    seed(db, reset=True)

    print("\n" + "="*60)
    print("  GTM-LOOP DEMO — Self-Improving GTM Agent")
    print("  Fully local, deterministic, no network calls")
    print("="*60)

    # -----------------------------------------------------------------------
    # Scene 1: Seed state
    # -----------------------------------------------------------------------
    _print_header("1", "Initial State")
    exps = db.execute("SELECT variant_id, segment, channel, tone FROM experiments").fetchall()
    print(f"  Experiments loaded: {len(exps)}")
    for e in exps:
        print(f"    - {e['variant_id']} ({e['segment']}, {e['channel']}, {e['tone']})")

    policy_row = db.execute("SELECT version, policy FROM policies ORDER BY version DESC LIMIT 1").fetchone()
    policy = json.loads(policy_row["policy"])
    print(f"\n  Policy v{policy_row['version']}:")
    print(f"    brevity={policy.get('brevity', 0.5):.2f}, "
          f"tone_assertiveness={policy.get('tone_assertiveness', 0.5):.2f}, "
          f"personalization_depth={policy.get('personalization_depth', 1)}")

    # -----------------------------------------------------------------------
    # Scene 2: Create opportunity + propose action
    # -----------------------------------------------------------------------
    _print_header("2", "Propose Action")

    db.execute(
        "INSERT INTO signals (id, company_id, type, payload, detected_at) "
        "VALUES ('sig-demo', 'c-acme', 'FUNDING', '{\"amount\":\"$5M Series A\"}', '2026-01-15T10:00:00')"
    )
    db.execute(
        "INSERT INTO opportunities (id, company_id, signal_id, status, score) "
        "VALUES ('opp-demo', 'c-acme', 'sig-demo', 'QUALIFIED', 0.85)"
    )
    db.commit()

    opp = db.execute("SELECT * FROM opportunities WHERE id = 'opp-demo'").fetchone()
    planned = plan_action(db, opp)

    if planned:
        gen = TemplateGenerator()
        # Get contact from company
        contact = db.execute(
            "SELECT * FROM contacts WHERE company_id = ? LIMIT 1",
            (opp["company_id"],)
        ).fetchone()
        signal = db.execute("SELECT * FROM signals WHERE id = ?", (opp["signal_id"],)).fetchone()
        # Get the experiment (variant) for the generator
        exp_row = db.execute(
            "SELECT * FROM experiments WHERE variant_id = ?",
            (planned.variant_id,)
        ).fetchone()
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
        draft = gen.generate(db, variant, dict(contact), dict(signal), policy)

        # Create action
        action_id = "act-demo-1"
        db.execute(
            "INSERT INTO actions (id, opportunity_id, contact_id, action_type, variant_id, "
            "channel, timing, mode, status, subject, body, cost_units, policy_version) "
            "VALUES (?, 'opp-demo', ?, ?, ?, ?, ?, 'PROPOSE', 'PROPOSED', ?, ?, 1, 1)",
            (action_id, contact["id"], planned.action_type.value, planned.variant_id,
             planned.channel.value, planned.timing.value, draft.subject, draft.body),
        )
        db.commit()

        # Decision card
        row = db.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
        card = build_decision_card(db, dict(row))
        _print_card(card)
        print(f"\n  Draft subject: {card.evidence[0] if card.evidence else 'N/A'}")
        print(f"  Draft body preview: {draft.body[:100]}...")
    else:
        print("  No action planned (no eligible opportunities)")

    # -----------------------------------------------------------------------
    # Scene 3: Human rejects with reason
    # -----------------------------------------------------------------------
    _print_header("3", "Human Rejects (too_salesy)")

    initial_tone = policy.get("tone_assertiveness", 0.5)
    print(f"  Initial tone_assertiveness: {initial_tone:.2f}")

    delta = apply_feedback(db, action_id, reason="too_salesy")
    policy_row = db.execute("SELECT version, policy FROM policies ORDER BY version DESC LIMIT 1").fetchone()
    policy = json.loads(policy_row["policy"])
    new_tone = policy.get("tone_assertiveness", 0.5)

    print(f"  Rejection reason: too_salesy")
    print(f"  Policy delta: tone_assertiveness {initial_tone:.2f} → {new_tone:.2f}")
    print(f"  Policy bumped to v{policy_row['version']}")

    # -----------------------------------------------------------------------
    # Scene 4: Execute + outcome
    # -----------------------------------------------------------------------
    _print_header("4", "Execute + Record Outcome")

    status = execute_action(db, action_id, "EMAIL")
    print(f"  Action executed: {status.value}")

    outcome = synthesize_outcome(db, action_id, warmth="warm")
    print(f"  Synthetic outcome: {outcome.result.value}")
    print(f"  Detail: {outcome.detail}")

    # -----------------------------------------------------------------------
    # Scene 5: Leaderboard
    # -----------------------------------------------------------------------
    _print_header("5", "Leaderboard (variant stats)")

    rows = db.execute("SELECT variant_id, stats FROM experiments").fetchall()
    print(f"  {'Variant':<40} {'Sent':>5} {'Replies':>8} {'Meetings':>9} {'Reply%':>7}")
    print(f"  {'-'*40} {'-'*5} {'-'*8} {'-'*9} {'-'*7}")
    for r in rows:
        stats = json.loads(r["stats"])
        sent = stats.get("sent", 0)
        replies = stats.get("replies", 0)
        meetings = stats.get("meetings", 0)
        rate = f"{replies/sent*100:.1f}%" if sent > 0 else "0.0%"
        print(f"  {r['variant_id']:<40} {sent:>5} {replies:>8} {meetings:>9} {rate:>7}")

    # -----------------------------------------------------------------------
    # Scene 6: Rollback demo
    # -----------------------------------------------------------------------
    _print_header("6", "Rollback Policy")

    print(f"  Current policy version: {policy_row['version']}")
    restored = rollback_policy(db)
    policy_row = db.execute("SELECT version, policy FROM policies ORDER BY version DESC LIMIT 1").fetchone()
    print(f"  Rolled back to version: {policy_row['version']}")
    print(f"  tone_assertiveness restored to: {json.loads(policy_row['policy']).get('tone_assertiveness', 0.5):.2f}")

    # -----------------------------------------------------------------------
    # Scene 7: Kill switch
    # -----------------------------------------------------------------------
    _print_header("7", "Kill Switch")

    print(f"  Current status: {get_control_status()}")
    set_control_status("paused")
    print(f"  After pause: {get_control_status()}")
    set_control_status("running")
    print(f"  After resume: {get_control_status()}")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    _print_header("DEMO", "Complete!")
    print("  The loop demonstrated:")
    print("    1. Signal detection and opportunity qualification")
    print("    2. Action planning and message generation")
    print("    3. Human feedback → policy mutation (tone decreased)")
    print("    4. Simulated execution and outcome recording")
    print("    5. Variant stats updated (leaderboard)")
    print("    6. Policy rollback (reverted to previous version)")
    print("    7. Kill switch (pause/resume)")
    print("\n  All behavior changes are persistent and testable.")
    print("  No network calls, no LLM, fully deterministic.\n")

    db.close()


if __name__ == "__main__":
    run_demo()
