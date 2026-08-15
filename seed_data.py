"""Deterministic synthetic world + playbook variants (PLAN.md task A3).

Seeds companies, contacts, warm-graph edges, and playbook experiments so the
demo is reproducible from a clean database. No real PII anywhere.
"""

from __future__ import annotations

import json
import random
import sqlite3
import uuid

from src.config import DB_PATH
from src.domain.enums import Channel, TimingSlot, ToneProfile, WarmthSignal
from src.store.db import connect

SEED = 42

COMPANIES = [
    # (id, name, segment, stage, employees, tags)
    ("c-acme", "Acme Analytics", "saas-b2b", "series-a", 48, ["data", "seed-funded"]),
    ("c-betacorp", "BetaCorp", "developer-tools", "growth", 120, ["v2", "devtools"]),
    ("c-gamma", "Gamma Systems", "fintech", "late", 340, ["rebrand", "enterprise"]),
    ("c-delta", "Delta Cloud", "infra", "series-a", 25, ["funding", "multi-cloud"]),
    ("c-epsilon", "Epsilon Labs", "ai", "seed", 12, ["research", "mlops"]),
    ("c-zeta", "Zeta Retail", "ecommerce", "growth", 210, ["expansion", "retail"]),
    ("c-eta", "Eta Health", "healthtech", "series-b", 95, ["compliance", "hipaa"]),
    ("c-theta", "Theta Security", "security", "series-a", 60, ["funding", "zero-trust"]),
]

CONTACTS = [
    # (id, company_id, name, title, warmth)
    ("p-acme-ceo", "c-acme", "Ava Chen", "CEO", WarmthSignal.COLD),
    ("p-acme-vp", "c-acme", "Ben Okafor", "VP Sales", WarmthSignal.COLD),
    ("p-betacorp-cto", "c-betacorp", "Clara Kim", "CTO", WarmthSignal.ENGAGED),
    ("p-betacorp-pm", "c-betacorp", "David Ruiz", "Head of Product", WarmthSignal.COLD),
    ("p-gamma-cmo", "c-gamma", "Elena Petrova", "CMO", WarmthSignal.COLD),
    ("p-gamma-vp", "c-gamma", "Frank Miller", "VP GTM", WarmthSignal.MET),
    ("p-delta-ceo", "c-delta", "Grace Liu", "CEO", WarmthSignal.COLD),
    ("p-epsilon-cto", "c-epsilon", "Hiro Tanaka", "CTO", WarmthSignal.COLD),
    ("p-zeta-cmo", "c-zeta", "Iris Novak", "CMO", WarmthSignal.ENGAGED),
    ("p-eta-cio", "c-eta", "James Osei", "CIO", WarmthSignal.COLD),
    ("p-theta-ceo", "c-theta", "Katie Berg", "CEO", WarmthSignal.COLD),
]

# Warm edges: (a, b, strength) — shared-connection graph for intro requests.
WARM_EDGES = [
    ("p-betacorp-cto", "p-gamma-vp", 0.8),
    ("p-gamma-vp", "p-zeta-cmo", 0.6),
    ("p-betacorp-cto", "p-acme-vp", 0.4),
]

VARIANTS = [
    # (variant_id, segment, template, channel, timing, tone, personalization_depth)
    ("v-saas-email-warm-morning", "saas-b2b",
     "Hi {name}, congrats on the {signal} at {company}. {personalization} Curious if a 20-min call makes sense this month?",
     Channel.EMAIL, TimingSlot.MORNING, ToneProfile.WARM, 2),
    ("v-saas-email-direct-morning", "saas-b2b",
     "{personalization} We help {segment} teams like {company} hit {metric}. Open to a quick benchmark?",
     Channel.EMAIL, TimingSlot.MORNING, ToneProfile.DIRECT, 1),
    ("v-saas-linkedin-warm-midday", "saas-b2b",
     "Hey {name} — saw {signal} at {company}. {personalization} Happy to share what we're seeing with similar teams.",
     Channel.LINKEDIN, TimingSlot.MIDDAY, ToneProfile.WARM, 1),
    ("v-devtools-email-warm-afternoon", "developer-tools",
     "Hi {name}, noticed {signal} — congrats. {personalization} Worth a 15-min look?",
     Channel.EMAIL, TimingSlot.AFTERNOON, ToneProfile.WARM, 2),
    ("v-devtools-email-direct-midday", "developer-tools",
     "{personalization} Dev teams at {company} scale — our tooling cuts {metric} by ~30% for similar orgs.",
     Channel.EMAIL, TimingSlot.MIDDAY, ToneProfile.DIRECT, 1),
    ("v-devtools-linkedin-direct-morning", "developer-tools",
     "Hi {name}, we help {segment} teams ship faster. {personalization} Thoughts?",
     Channel.LINKEDIN, TimingSlot.MORNING, ToneProfile.DIRECT, 1),
    ("v-fintech-email-warm-morning", "fintech",
     "Hi {name}, the {signal} at {company} caught my eye. {personalization} Open to a 20-min call?",
     Channel.EMAIL, TimingSlot.MORNING, ToneProfile.WARM, 2),
    ("v-fintech-linkedin-warm-afternoon", "fintech",
     "Hi {name} — {signal} at {company} looks promising. {personalization} Would love to compare notes.",
     Channel.LINKEDIN, TimingSlot.AFTERNOON, ToneProfile.WARM, 1),
]

# Multi-touch sequences (Issue #44): ordered steps with delay windows.
SEQUENCES = [
    # (sequence_id, name, segment, steps=[(action_type, channel, delay_days, hint), ...])
    ("seq-saas-email", "SaaS Email Intro Sequence", "saas-b2b", [
        ("OUTREACH_EMAIL", Channel.EMAIL, 0, "intro"),
        ("FOLLOW_UP", Channel.EMAIL, 3, "first follow-up"),
        ("FOLLOW_UP", Channel.EMAIL, 7, "second follow-up"),
    ]),
    ("seq-saas-cross", "SaaS Cross-Channel", "saas-b2b", [
        ("OUTREACH_EMAIL", Channel.EMAIL, 0, "intro"),
        ("LINKEDIN_CONNECT", Channel.LINKEDIN, 3, "connect on LinkedIn"),
        ("FOLLOW_UP", Channel.EMAIL, 7, "second follow-up"),
    ]),
    ("seq-devtools-email", "DevTools Email Sequence", "developer-tools", [
        ("OUTREACH_EMAIL", Channel.EMAIL, 0, "intro"),
        ("FOLLOW_UP", Channel.EMAIL, 2, "first follow-up"),
        ("FOLLOW_UP", Channel.EMAIL, 6, "break-up email"),
    ]),
    ("seq-fintech-cross", "Fintech Cross-Channel", "fintech", [
        ("OUTREACH_EMAIL", Channel.EMAIL, 0, "intro"),
        ("LINKEDIN_CONNECT", Channel.LINKEDIN, 4, "connect on LinkedIn"),
        ("FOLLOW_UP", Channel.EMAIL, 8, "break-up email"),
    ]),
]


def _seed_sequences(conn: sqlite3.Connection) -> None:
    for sequence_id, name, segment, steps in SEQUENCES:
        conn.execute(
            "INSERT INTO sequences (sequence_id, name, segment, stats, max_steps) "
            "VALUES (?, ?, ?, ?, ?)",
            (sequence_id, name, segment, json.dumps({"sent": 0, "replies": 0, "meetings": 0}), len(steps)),
        )
        for order, (action_type, channel, delay, hint) in enumerate(steps, start=1):
            conn.execute(
                "INSERT INTO sequence_steps (sequence_id, step_order, action_type, channel, delay_days, content_hint) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sequence_id, order, action_type, channel.value, delay, hint),
            )


def seed(conn: sqlite3.Connection | None = None, rng_seed: int = SEED, reset: bool = True) -> sqlite3.Connection:
    """Populate the store with the deterministic synthetic world.

    Returns the connection. When reset=True (default) all domain tables are
    cleared first so a demo always starts from a known state.
    """
    if conn is None:
        conn = connect()
    rng = random.Random(rng_seed)
    if reset:
        for table in ("sequence_steps", "sequences", "warm_edges", "outcomes", "activity",
                      "actions", "opportunities", "signals", "contacts", "companies",
                      "experiments", "policies", "memory_kv"):
            conn.execute(f"DELETE FROM {table}")

    for cid, name, segment, stage, emp, tags in COMPANIES:
        conn.execute(
            "INSERT INTO companies (id, name, segment, stage, employees, tags) VALUES (?,?,?,?,?,?)",
            (cid, name, segment, stage, emp, json.dumps(tags)),
        )
    for pid, cid, name, title, warmth in CONTACTS:
        email = f"{name.lower().replace(' ', '.')}@{cid.split('-')[1]}.example.com"
        conn.execute(
            "INSERT INTO contacts (id, company_id, name, title, email, linkedin, warmth) VALUES (?,?,?,?,?,?,?)",
            (pid, cid, name, title, email, f"https://linkedin.com/in/{pid}", warmth.value),
        )
    for a, b, strength in WARM_EDGES:
        conn.execute(
            "INSERT INTO warm_edges (contact_a, contact_b, strength, direction, source) VALUES (?,?,?,?,?)",
            (a, b, strength, "mutual", "seed"),
        )
    for variant_id, segment, template, channel, timing, tone, depth in VARIANTS:
        conn.execute(
            "INSERT INTO experiments (variant_id, segment, template, channel, timing, tone, personalization_depth, stats) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (variant_id, segment, template, channel.value, timing.value, tone.value, depth, json.dumps({"sent": 0, "replies": 0, "meetings": 0, "positive": 0, "negative": 0, "unsub": 0})),
        )
    _seed_sequences(conn)
    conn.execute(
        "INSERT INTO policies (version, policy, source) VALUES (1, ?, 'initial')",
        (json.dumps({
            "brevity": 0.5,
            "tone_assertiveness": 0.5,
            "personalization_depth": 1,
            "funding_led_hooks": 0.5,
            "channel_prior": {c.value: 0.5 for c in Channel},
            "timing_prior": {t.value: 1 / len(TimingSlot) for t in TimingSlot},
        }),),
    )
    conn.commit()
    return conn


if __name__ == "__main__":
    conn = seed()
    counts = {
        t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
        for t in ("companies", "contacts", "warm_edges", "experiments", "policies")
    }
    print("Seeded:", counts)
    conn.close()
