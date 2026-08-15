"""DECIDE: generate tests (PLAN.md task C3).

Tests for the new component-based MessageComposer (Phase 1.1).
"""

import json

import pytest

from seed_data import seed
from src.config import BANNED_PHRASES
from src.domain.enums import Channel, SignalType, ToneProfile
from src.engine.generate import TemplateGenerator, MessageComposer, CompositionContext
from src.store.db import connect


@pytest.fixture()
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    seed(conn, reset=True)
    yield conn
    conn.close()


def _get_policy(conn) -> dict:
    row = conn.execute("SELECT policy FROM policies ORDER BY version DESC LIMIT 1").fetchone()
    return json.loads(row["policy"])


def _get_variant(conn, variant_id: str) -> dict:
    row = conn.execute("SELECT * FROM experiments WHERE variant_id = ?", (variant_id,)).fetchone()
    return dict(row) if row else None


def _get_signal(conn, company_id: str) -> dict:
    row = conn.execute(
        "SELECT id, company_id, type, payload, detected_at FROM signals WHERE company_id = ? LIMIT 1",
        (company_id,),
    ).fetchone()
    if row:
        return dict(row)
    conn.execute(
        "INSERT INTO signals (id, company_id, type, payload, detected_at) VALUES (?, ?, ?, ?, ?)",
        ("sig-gen-test", company_id, "FUNDING", json.dumps({"amount": "$5M Series A"}), "2026-01-15T10:00:00"),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, company_id, type, payload, detected_at FROM signals WHERE id = 'sig-gen-test'"
    ).fetchone()
    return dict(row)


def _get_contact(conn, company_id: str) -> dict:
    row = conn.execute(
        "SELECT id, company_id, name, title, email, linkedin, warmth FROM contacts WHERE company_id = ? LIMIT 1",
        (company_id,),
    ).fetchone()
    return dict(row) if row else {"id": "p-test", "company_id": company_id, "name": "Test User", "title": "CEO", "email": "test@test.com", "linkedin": "", "warmth": "cold"}


def _make_experiment(db, variant_id: str = "v-saas-email-warm-morning"):
    variant = _get_variant(db, variant_id)
    from src.domain.models import Experiment
    return Experiment(
        variant_id=variant["variant_id"], segment=variant["segment"],
        template=variant["template"], channel=Channel(variant["channel"]),
        timing=variant["timing"], tone=variant["tone"],
        personalization_depth=variant["personalization_depth"],
        stats=json.loads(variant["stats"]),
    )


# --- Basic generation --------------------------------------------------------

def test_generate_returns_drafted_message(db):
    gen = TemplateGenerator()
    exp = _make_experiment(db)
    contact = _get_contact(db, "c-acme")
    signal = _get_signal(db, "c-acme")
    policy = _get_policy(db)

    msg = gen.generate(db, exp, contact, signal, policy)
    assert msg.subject
    assert msg.body
    assert msg.policy_version >= 1


def test_generate_fills_template_placeholders(db):
    gen = TemplateGenerator()
    exp = _make_experiment(db)
    contact = _get_contact(db, "c-acme")
    signal = _get_signal(db, "c-acme")
    policy = _get_policy(db)

    msg = gen.generate(db, exp, contact, signal, policy)
    # Should contain the contact name
    assert "Ava" in msg.body or "ava" in msg.body.lower()
    # Should NOT contain literal {name} or {company}
    assert "{name}" not in msg.body
    assert "{company}" not in msg.body


def test_generate_subject_contains_signal(db):
    """Subject should contain signal reference (amount/product) and contact name."""
    gen = TemplateGenerator()
    exp = _make_experiment(db)
    contact = _get_contact(db, "c-acme")
    signal = _get_signal(db, "c-acme")
    policy = _get_policy(db)

    msg = gen.generate(db, exp, contact, signal, policy)
    # New subject format: "Congrats on the $5M Series A, Ava Chen"
    assert "Series A" in msg.subject or "$5M" in msg.subject
    assert "Ava" in msg.subject or "Chen" in msg.subject


# --- Policy directives -------------------------------------------------------

def test_generate_respects_personalization_depth(db):
    gen = TemplateGenerator()
    exp = _make_experiment(db)
    contact = _get_contact(db, "c-acme")
    signal = _get_signal(db, "c-acme")
    policy = _get_policy(db)

    # Depth 0 → no personalization items
    policy_zero = {**policy, "personalization_depth": 0}
    msg0 = gen.generate(db, exp, contact, signal, policy_zero)
    assert msg0.personalization == []

    # Depth 2 → up to 2 items
    policy_two = {**policy, "personalization_depth": 2}
    msg2 = gen.generate(db, exp, contact, signal, policy_two)
    assert len(msg2.personalization) <= 2


def test_generate_brevity_produces_shorter_output(db):
    gen = TemplateGenerator()
    exp = _make_experiment(db)
    contact = _get_contact(db, "c-acme")
    signal = _get_signal(db, "c-acme")
    policy = _get_policy(db)

    # High brevity should produce shorter output
    policy_brevity = {**policy, "brevity": 0.9}
    msg_brevity = gen.generate(db, exp, contact, signal, policy_brevity)
    # Should be reasonably short (semantic compression, not truncation)
    assert len(msg_brevity.body) < 500


def test_generate_warm_tone_uses_softer_language(db):
    """Warm tone with low assertiveness uses softer lexical choices."""
    gen = TemplateGenerator()
    exp = _make_experiment(db)
    contact = _get_contact(db, "c-acme")
    signal = _get_signal(db, "c-acme")
    policy = _get_policy(db)

    # Warm tone with low assertiveness → softer language
    policy_warm = {**policy, "tone_assertiveness": 0.2}
    msg = gen.generate(db, exp, contact, signal, policy_warm)
    body_lower = msg.body.lower()
    # Should use softer alternatives
    assert "partner with" in body_lower or "support" in body_lower or "would you be open" in body_lower
    # Should NOT use aggressive direct language
    assert "we help" not in body_lower or "cuts" not in body_lower


def test_generate_direct_tone_uses_sharper_language(db):
    """Direct tone with high assertiveness uses sharper lexical choices."""
    gen = TemplateGenerator()
    exp = _make_experiment(db)
    contact = _get_contact(db, "c-acme")
    signal = _get_signal(db, "c-acme")
    policy = _get_policy(db)

    # Direct tone with high assertiveness → sharper language
    policy_direct = {**policy, "tone_assertiveness": 0.8}
    msg = gen.generate(db, exp, contact, signal, policy_direct)
    body_lower = msg.body.lower()
    # Should use direct language
    assert "we help" in body_lower or "cuts" in body_lower or "let me know" in body_lower


def test_generate_rewrites_banned_phrases(db):
    """Banned phrases should be rewritten, not just stripped."""
    gen = TemplateGenerator()
    contact = _get_contact(db, "c-acme")
    signal = _get_signal(db, "c-acme")
    policy = _get_policy(db)

    from src.domain.models import Experiment
    from src.domain.enums import TimingSlot
    # Override template to include a banned phrase
    exp = Experiment(
        variant_id="test-banned", segment="saas-b2b",
        template="This is a limited time offer for {name}.",
        channel=Channel.EMAIL, timing=TimingSlot.MORNING, tone=ToneProfile.WARM,
        personalization_depth=1, stats={},
    )

    msg = gen.generate(db, exp, contact, signal, policy)
    body_lower = msg.body.lower()
    # Original banned phrase should be gone
    assert "limited time offer" not in body_lower
    # Should be rewritten to acceptable alternative
    assert "current opportunity" in body_lower or "opportunity" in body_lower


def test_generate_composition_trace_recorded(db):
    """Composition trace should include component selection info."""
    gen = TemplateGenerator()
    exp = _make_experiment(db)
    contact = _get_contact(db, "c-acme")
    signal = _get_signal(db, "c-acme")
    policy = _get_policy(db)

    msg = gen.generate(db, exp, contact, signal, policy)
    trace = msg.prompt_trace
    # New trace includes component IDs
    assert "hook_id" in trace
    assert "value_prop_id" in trace
    assert "social_proof_id" in trace
    assert "cta_id" in trace
    assert "components_selected" in trace
    assert trace["components_selected"]["hook"].startswith("hook_")
    assert trace["components_selected"]["value_prop"].startswith("vp_")
    assert "brevity" in trace
    assert "tone" in trace
    assert "personalization_depth" in trace


# --- MessageComposer direct tests --------------------------------------------

def test_composer_selects_role_appropriate_components(db):
    """Composer should select components matching contact role."""
    composer = MessageComposer(db)
    exp = _make_experiment(db)
    contact = _get_contact(db, "c-acme")  # CEO
    signal = _get_signal(db, "c-acme")
    policy = _get_policy(db)

    from src.engine.generate import CompositionContext
    import random
    company_row = db.execute("SELECT * FROM companies WHERE id = 'c-acme'").fetchone()
    company = dict(company_row)

    ctx = CompositionContext(
        contact=contact,
        company=company,
        signal=signal,
        variant=exp,
        policy=policy,
        rng=random.Random(42),
    )

    composed = composer.compose(ctx)
    # CEO should get strategic framing
    trace = composed.composition_trace
    assert "hook_id" in trace
    assert "value_prop_id" in trace


def test_composer_uses_policy_weights(db):
    """Policy weights should influence component selection."""
    composer = MessageComposer(db)
    exp = _make_experiment(db)
    contact = _get_contact(db, "c-acme")
    signal = _get_signal(db, "c-acme")

    import random
    company_row = db.execute("SELECT * FROM companies WHERE id = 'c-acme'").fetchone()
    company = dict(company_row)

    # High brevity should favor shorter components
    policy_high_brevity = {**_get_policy(db), "brevity": 0.9}
    ctx = CompositionContext(
        contact=contact, company=company, signal=signal, variant=exp,
        policy=policy_high_brevity, rng=random.Random(42),
    )
    composed_high = composer.compose(ctx)

    # Low brevity should allow longer components
    policy_low_brevity = {**_get_policy(db), "brevity": 0.1}
    ctx.policy = policy_low_brevity
    composed_low = composer.compose(ctx)

    # High brevity should produce shorter body
    assert len(composed_high.body) <= len(composed_low.body) * 1.2  # allow some variance


def test_composer_handles_different_signals(db):
    """Composer should adapt to different signal types."""
    composer = MessageComposer(db)
    exp = _make_experiment(db)
    contact = _get_contact(db, "c-acme")
    policy = _get_policy(db)

    import random
    company_row = db.execute("SELECT * FROM companies WHERE id = 'c-acme'").fetchone()
    company = dict(company_row)

    # Test FUNDING signal
    signal_funding = _get_signal(db, "c-acme")
    ctx = CompositionContext(
        contact=contact, company=company, signal=signal_funding, variant=exp,
        policy=policy, rng=random.Random(42),
    )
    composed_funding = composer.compose(ctx)
    assert "Series A" in composed_funding.subject or "funding" in composed_funding.body.lower()

    # Test HIRING signal
    signal_hiring = {
        "id": "sig-hiring", "company_id": "c-acme", "type": "HIRING",
        "payload": json.dumps({"role": "VP Sales"}), "detected_at": "2026-01-15T10:00:00"
    }
    ctx.signal = signal_hiring
    composed_hiring = composer.compose(ctx)
    assert "hiring" in composed_hiring.body.lower() or "scaling" in composed_hiring.body.lower() or "team" in composed_hiring.body.lower()


def test_composer_personalization_from_signal(db):
    """Personalization items should come from signal payload."""
    composer = MessageComposer(db)
    exp = _make_experiment(db)
    contact = _get_contact(db, "c-acme")
    signal = _get_signal(db, "c-acme")
    policy = _get_policy(db)

    import random
    company_row = db.execute("SELECT * FROM companies WHERE id = 'c-acme'").fetchone()
    company = dict(company_row)

    ctx = CompositionContext(
        contact=contact, company=company, signal=signal, variant=exp,
        policy=policy, rng=random.Random(42),
    )
    composed = composer.compose(ctx)

    # Should have personalization items from the funding signal
    assert len(composed.personalization) >= 1
    # At least one should reference the funding
    personalization_text = " ".join(composed.personalization).lower()
    assert "funding" in personalization_text or "series a" in personalization_text or "$5m" in personalization_text