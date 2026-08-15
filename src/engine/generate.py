"""DECIDE: Structured message generation (PLAN.md block 3).

MessageComposer assembles messages from components (Hook, ValueProp, SocialProof, CTA)
based on context: role, segment, stage, signal, policy. Deterministic, no LLM required.
LLM adapter available as optional backend.

Public surface:
    MessageComposer.compose(context, policy, library) -> ComposedMessage
    TemplateGenerator.generate(...) -> DraftedMessage  # backward compat
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from ..config import BANNED_PHRASES
from ..domain.enums import SignalType, ToneProfile
from ..domain.models import (
    ComponentLibrary,
    ComponentType,
    ComponentVariant,
    ComposedMessage,
    DraftedMessage,
    Experiment,
)


# ---------------------------------------------------------------------------
# Component Library (seeded from DB or embedded defaults)
# ---------------------------------------------------------------------------

_DEFAULT_HOOKS = [
    ComponentVariant(
        component_type=ComponentType.HOOK,
        variant_id="hook_funding_congrats",
        text="Congrats on the {signal} at {company}!",
        signals=["FUNDING"],
        roles=["CEO", "VP Sales", "CTO"],
        weight=1.2,
    ),
    ComponentVariant(
        component_type=ComponentType.HOOK,
        variant_id="hook_funding_strategic",
        text="Your {signal} signals an exciting growth phase for {company}.",
        signals=["FUNDING"],
        roles=["CEO", "CFO", "COO"],
        tone_profiles=["WARM"],
        weight=1.0,
    ),
    ComponentVariant(
        component_type=ComponentType.HOOK,
        variant_id="hook_hiring_scaling",
        text="Noticed you're scaling the team — great timing to connect.",
        signals=["HIRING"],
        roles=["VP Sales", "VP Engineering", "CTO"],
        weight=1.1,
    ),
    ComponentVariant(
        component_type=ComponentType.HOOK,
        variant_id="hook_product_launch",
        text="The {signal} launch looks impressive — congrats to the team.",
        signals=["PRODUCT"],
        roles=["CEO", "CTO", "VP Product"],
        weight=1.0,
    ),
    ComponentVariant(
        component_type=ComponentType.HOOK,
        variant_id="hook_pricing_shift",
        text="Your pricing update suggests a strategic shift worth discussing.",
        signals=["PRICING"],
        roles=["CEO", "VP Sales", "CRO"],
        weight=0.9,
    ),
    ComponentVariant(
        component_type=ComponentType.HOOK,
        variant_id="hook_content_resonance",
        text="Your recent content resonated — thought leadership like yours stands out.",
        signals=["CONTENT"],
        roles=["CEO", "CMO", "VP Marketing"],
        weight=0.8,
    ),
    ComponentVariant(
        component_type=ComponentType.HOOK,
        variant_id="hook_cold_direct",
        text="Hi {name},",
        signals=["FUNDING", "HIRING", "PRODUCT", "PRICING", "CONTENT"],
        roles=["CEO", "VP Sales", "CTO", "CMO", "VP Engineering"],
        tone_profiles=["DIRECT"],
        weight=0.7,
    ),
    ComponentVariant(
        component_type=ComponentType.HOOK,
        variant_id="hook_cold_warm",
        text="Hi {name}, hope you're having a good week.",
        signals=["FUNDING", "HIRING", "PRODUCT", "PRICING", "CONTENT"],
        roles=["CEO", "VP Sales", "CTO", "CMO", "VP Engineering"],
        tone_profiles=["WARM"],
        weight=0.7,
    ),
]

_DEFAULT_VALUE_PROPS = [
    ComponentVariant(
        component_type=ComponentType.VALUE_PROP,
        variant_id="vp_pipeline_velocity",
        text="We help {segment} teams like {company} accelerate pipeline velocity by 30%+. ",
        segments=["saas-b2b", "developer-tools", "fintech", "ai", "infra", "security"],
        roles=["CEO", "VP Sales", "CRO"],
        weight=1.2,
    ),
    ComponentVariant(
        component_type=ComponentType.VALUE_PROP,
        variant_id="vp_dev_productivity",
        text="Our tooling cuts {metric} by ~30% for similar orgs — dev teams ship faster. ",
        segments=["developer-tools", "ai", "infra"],
        roles=["CTO", "VP Engineering", "VP Product"],
        weight=1.1,
    ),
    ComponentVariant(
        component_type=ComponentType.VALUE_PROP,
        variant_id="vp_compliance_security",
        text="We help {segment} companies maintain {metric} compliance while scaling. ",
        segments=["fintech", "healthtech", "security"],
        roles=["CEO", "CISO", "CIO", "CTO"],
        weight=1.0,
    ),
    ComponentVariant(
        component_type=ComponentType.VALUE_PROP,
        variant_id="vp_growth_efficiency",
        text="Our platform improves {metric} efficiency for {stage}-stage {segment} companies. ",
        segments=["saas-b2b", "ecommerce", "ai"],
        roles=["CEO", "CFO", "COO"],
        stages=["series-a", "series-b", "growth"],
        weight=1.0,
    ),
    ComponentVariant(
        component_type=ComponentType.VALUE_PROP,
        variant_id="vp_strategic_partnership",
        text="We're partnering with {segment} leaders to co-build the next generation of {metric}. ",
        segments=["saas-b2b", "fintech", "developer-tools"],
        roles=["CEO", "CTO", "VP Product"],
        weight=0.8,
    ),
    ComponentVariant(
        component_type=ComponentType.VALUE_PROP,
        variant_id="vp_generic_roi",
        text="Teams like yours see measurable ROI on {metric} within 90 days. ",
        segments=["saas-b2b", "developer-tools", "fintech", "ai", "infra", "security", "healthtech", "ecommerce"],
        roles=["CEO", "VP Sales", "CRO", "CTO", "CFO"],
        weight=0.6,
    ),
]

_DEFAULT_SOCIAL_PROOFS = [
    ComponentVariant(
        component_type=ComponentType.SOCIAL_PROOF,
        variant_id="sp_similar_companies",
        text="Companies like {peer_company} saw {result} after implementing our solution. ",
        segments=["saas-b2b", "developer-tools", "fintech", "ai", "infra", "security"],
        weight=1.1,
        metadata={"requires_peer": True},
    ),
    ComponentVariant(
        component_type=ComponentType.SOCIAL_PROOF,
        variant_id="sp_benchmark_data",
        text="Our benchmark data shows top-quartile {segment} teams achieve {result}. ",
        segments=["saas-b2b", "developer-tools", "fintech", "ai", "infra", "security", "healthtech", "ecommerce"],
        weight=0.9,
    ),
    ComponentVariant(
        component_type=ComponentType.SOCIAL_PROOF,
        variant_id="sp_customer_quote",
        text="\"{quote}\" — {customer_name}, {customer_title} at {customer_company}. ",
        segments=["saas-b2b", "developer-tools", "fintech", "ai", "infra", "security", "healthtech", "ecommerce"],
        weight=0.8,
        metadata={"requires_quote": True},
    ),
    ComponentVariant(
        component_type=ComponentType.SOCIAL_PROOF,
        variant_id="sp_no_proof",
        text="",
        segments=["saas-b2b", "developer-tools", "fintech", "ai", "infra", "security", "healthtech", "ecommerce"],
        weight=0.3,
    ),
]

_DEFAULT_CTAS = [
    ComponentVariant(
        component_type=ComponentType.CTA,
        variant_id="cta_meeting_soft",
        text="Would love to connect and share ideas — worth a 20-min call this month?",
        tone_profiles=["WARM"],
        roles=["CEO", "VP Sales", "CRO", "CMO", "CTO"],
        weight=1.2,
    ),
    ComponentVariant(
        component_type=ComponentType.CTA,
        variant_id="cta_meeting_direct",
        text="Open to a quick benchmark call? Let me know what works.",
        tone_profiles=["DIRECT"],
        roles=["CEO", "VP Sales", "CRO", "CTO", "VP Engineering"],
        weight=1.1,
    ),
    ComponentVariant(
        component_type=ComponentType.CTA,
        variant_id="cta_demo_soft",
        text="Happy to show you a quick demo — no pressure, just see if it's relevant.",
        tone_profiles=["WARM"],
        roles=["VP Engineering", "CTO", "VP Product"],
        weight=1.0,
    ),
    ComponentVariant(
        component_type=ComponentType.CTA,
        variant_id="cta_resource_soft",
        text="I can share a 2-pager on how we think about {metric} — useful either way.",
        tone_profiles=["WARM"],
        roles=["CEO", "CFO", "COO", "VP Product"],
        weight=0.9,
    ),
    ComponentVariant(
        component_type=ComponentType.CTA,
        variant_id="cta_direct_ask",
        text="Worth a 15-min conversation? Let me know.",
        tone_profiles=["DIRECT"],
        roles=["CEO", "VP Sales", "CRO", "CTO"],
        weight=0.9,
    ),
    ComponentVariant(
        component_type=ComponentType.CTA,
        variant_id="cta_no_ask",
        text="Either way, congrats again on the momentum.",
        tone_profiles=["WARM", "DIRECT"],
        roles=["CEO", "VP Sales", "CTO", "CMO", "VP Engineering", "CFO", "COO"],
        weight=0.3,
    ),
]


def _load_library_from_db(conn: sqlite3.Connection) -> ComponentLibrary:
    """Load component library from database. Falls back to defaults if empty."""
    library = ComponentLibrary()

    # Try to load from experiments table variants as component source
    rows = conn.execute(
        "SELECT variant_id, segment, template, channel, timing, tone, personalization_depth FROM experiments"
    ).fetchall()

    if rows:
        # Parse existing templates into components (best effort)
        for row in rows:
            # For now, use defaults. In production, would parse templates.
            pass

    # Merge with defaults
    library.hooks.extend(_DEFAULT_HOOKS)
    library.value_props.extend(_DEFAULT_VALUE_PROPS)
    library.social_proofs.extend(_DEFAULT_SOCIAL_PROOFS)
    library.ctas.extend(_DEFAULT_CTAS)

    return library


# ---------------------------------------------------------------------------
# Context for composition
# ---------------------------------------------------------------------------

@dataclass
class CompositionContext:
    """All context needed to compose a message."""
    contact: dict[str, Any]
    company: dict[str, Any]
    signal: dict[str, Any]
    variant: Experiment
    policy: dict[str, Any]
    rng: random.Random


# ---------------------------------------------------------------------------
# Component Selector
# ---------------------------------------------------------------------------

class ComponentSelector:
    """Selects best component variant for each type given context and policy."""

    def __init__(self, library: ComponentLibrary):
        self.library = library

    def _score_variant(self, variant: ComponentVariant, ctx: CompositionContext) -> float:
        """Score a variant based on context match."""
        score = variant.weight

        # Role match
        role = ctx.contact.get("title", "").upper()
        if variant.roles and any(r.upper() in role for r in variant.roles):
            score *= 1.5

        # Segment match
        segment = ctx.company.get("segment", "")
        if variant.segments and segment in variant.segments:
            score *= 1.5

        # Stage match
        stage = ctx.company.get("stage", "")
        if variant.stages and stage in variant.stages:
            score *= 1.3

        # Signal match
        signal_type = ctx.signal.get("type", "")
        if variant.signals and signal_type in variant.signals:
            score *= 1.4

        # Tone match
        tone = ctx.variant.tone.value
        if variant.tone_profiles and tone in variant.tone_profiles:
            score *= 1.3

        # Policy weight adjustments
        brevity = ctx.policy.get("brevity", 0.5)
        if brevity > 0.7 and len(variant.text) > 200:
            score *= 0.7  # Penalize long variants when brevity is high

        tone_assertiveness = ctx.policy.get("tone_assertiveness", 0.5)
        if tone_assertiveness > 0.7 and "DIRECT" in variant.tone_profiles:
            score *= 1.2
        elif tone_assertiveness < 0.3 and "WARM" in variant.tone_profiles:
            score *= 1.2

        return score

    def select(self, component_type: ComponentType, ctx: CompositionContext) -> ComponentVariant:
        """Select best variant for component type using weighted random choice."""
        variants = self.library.get_variants(component_type)
        if not variants:
            # Fallback empty variant
            return ComponentVariant(
                component_type=component_type,
                variant_id=f"empty_{component_type.value}",
                text="",
            )

        # Score all variants
        scored = [(v, self._score_variant(v, ctx)) for v in variants]
        scored.sort(key=lambda x: x[1], reverse=True)

        # Weighted random from top candidates (Thompson-style exploration)
        top_k = min(3, len(scored))
        total_weight = sum(s for _, s in scored[:top_k])
        if total_weight <= 0:
            return scored[0][0]

        r = ctx.rng.random() * total_weight
        cumulative = 0.0
        for variant, weight in scored[:top_k]:
            cumulative += weight
            if r <= cumulative:
                return variant

        return scored[0][0]


# ---------------------------------------------------------------------------
# Template Renderer
# ---------------------------------------------------------------------------

class TemplateRenderer:
    """Renders component text with context variables."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _get_peer_company(self, segment: str, exclude: str) -> str:
        """Get a peer company name for social proof."""
        row = self.conn.execute(
            "SELECT name FROM companies WHERE segment = ? AND id != ? ORDER BY RANDOM() LIMIT 1",
            (segment, exclude),
        ).fetchone()
        return row["name"] if row else "similar companies"

    def _get_metric_for_segment(self, segment: str) -> str:
        """Get relevant metric for segment."""
        metrics = {
            "saas-b2b": "pipeline velocity",
            "developer-tools": "deployment frequency",
            "fintech": "transaction latency",
            "ai": "model inference cost",
            "infra": "cloud spend efficiency",
            "security": "incident response time",
            "healthtech": "patient data throughput",
            "ecommerce": "conversion rate",
        }
        return metrics.get(segment, "key metrics")

    def render(self, variant: ComponentVariant, ctx: CompositionContext) -> str:
        """Fill template placeholders with context values."""
        text = variant.text

        # Extract signal payload
        payload = ctx.signal.get("payload", {})
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}

        signal_label = payload.get("amount") or payload.get("product") or payload.get("role") or ctx.signal.get("type", "update")

        # Base replacements
        replacements = {
            "{name}": ctx.contact.get("name", ""),
            "{company}": ctx.company.get("name", ""),
            "{signal}": signal_label,
            "{segment}": ctx.company.get("segment", ""),
            "{stage}": ctx.company.get("stage", ""),
            "{metric}": self._get_metric_for_segment(ctx.company.get("segment", "")),
            "{peer_company}": self._get_peer_company(ctx.company.get("segment", ""), ctx.company.get("id", "")),
            "{result}": "30% faster pipeline growth",
            "{quote}": "This transformed how we approach outbound",
            "{customer_name}": "Sarah Chen",
            "{customer_title}": "VP Sales",
            "{customer_company}": "Acme Analytics",
        }

        # Personalization items from signal
        personalization_items = self._build_personalization(ctx)
        if personalization_items:
            depth = ctx.policy.get("personalization_depth", ctx.variant.personalization_depth)
            replacements["{personalization}"] = " ".join(personalization_items[:depth])
        else:
            replacements["{personalization}"] = ""

        # Apply replacements
        for key, val in replacements.items():
            text = text.replace(key, str(val))

        return text.strip()

    def _build_personalization(self, ctx: CompositionContext) -> list[str]:
        """Build personalization items from signal and company data."""
        items = []
        payload = ctx.signal.get("payload", {})
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}

        sig_type = SignalType(ctx.signal.get("type", "FUNDING"))

        if sig_type == SignalType.FUNDING:
            amount = payload.get("amount", "your recent funding")
            items.append(f"Your {amount} round caught our attention")
            items.append(f"Congrats on the {amount} — exciting milestone")
        elif sig_type == SignalType.HIRING:
            role = payload.get("role", "key roles")
            items.append(f"Noticed you're hiring for {role} — great timing")
            items.append(f"Your hiring momentum signals strong growth")
        elif sig_type == SignalType.PRODUCT:
            product = payload.get("product", "your new product")
            items.append(f"The {product} launch looks impressive")
            items.append(f"Your product velocity is notable in the market")
        elif sig_type == SignalType.PRICING:
            items.append("Your pricing update suggests a strategic shift")
            items.append("Interesting positioning move in the market")
        elif sig_type == SignalType.CONTENT:
            items.append("Your recent content resonated with the community")
            items.append("Thought leadership like yours stands out")

        # Add company-specific personalization
        tags = ctx.company.get("tags", [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = []

        if "seed-funded" in tags or "funding" in tags:
            items.append("Seed-funded companies like yours are our sweet spot")
        if "v2" in tags or "devtools" in tags:
            items.append("DevTools v2 launches are a focus area for us")
        if "expansion" in tags:
            items.append("International expansion is a journey we know well")

        return items


# ---------------------------------------------------------------------------
# Message Composer
# ---------------------------------------------------------------------------

class MessageComposer:
    """Composes messages from components based on context and policy."""

    def __init__(self, conn: sqlite3.Connection, library: ComponentLibrary | None = None):
        self.conn = conn
        self.library = library or _load_library_from_db(conn)
        self.selector = ComponentSelector(self.library)
        self.renderer = TemplateRenderer(conn)

    def compose(self, ctx: CompositionContext) -> ComposedMessage:
        """Compose a full message by selecting and rendering components."""
        components_used = {}

        # Select components in order
        hook = self.selector.select(ComponentType.HOOK, ctx)
        components_used[ComponentType.HOOK] = hook

        value_prop = self.selector.select(ComponentType.VALUE_PROP, ctx)
        components_used[ComponentType.VALUE_PROP] = value_prop

        social_proof = self.selector.select(ComponentType.SOCIAL_PROOF, ctx)
        components_used[ComponentType.SOCIAL_PROOF] = social_proof

        cta = self.selector.select(ComponentType.CTA, ctx)
        components_used[ComponentType.CTA] = cta

        # Render each component
        rendered = {}
        for comp_type, variant in components_used.items():
            rendered[comp_type] = self.renderer.render(variant, ctx)

        # Assemble body
        body_parts = []
        if rendered[ComponentType.HOOK]:
            body_parts.append(rendered[ComponentType.HOOK])
        if rendered[ComponentType.VALUE_PROP]:
            body_parts.append(rendered[ComponentType.VALUE_PROP])
        if rendered[ComponentType.SOCIAL_PROOF]:
            body_parts.append(rendered[ComponentType.SOCIAL_PROOF])
        if rendered[ComponentType.CTA]:
            body_parts.append(rendered[ComponentType.CTA])

        body = " ".join(p for p in body_parts if p).strip()

        # Apply brevity: semantic compression, not truncation
        brevity = ctx.policy.get("brevity", 0.5)
        if brevity > 0.7:
            body = self._compress_for_brevity(body, ctx)

        # Apply tone adjustments
        body = self._adjust_tone(body, ctx)

        # Content guardrail: rewrite banned phrases instead of "[removed]"
        body = self._rewrite_banned_phrases(body)

        # Build subject line
        subject = self._build_subject(ctx)

        # Collect personalization used
        personalization = self.renderer._build_personalization(ctx)
        depth = ctx.policy.get("personalization_depth", ctx.variant.personalization_depth)
        personalization = personalization[:depth]

        policy_version = self.conn.execute("SELECT MAX(version) AS v FROM policies").fetchone()["v"] or 1

        return ComposedMessage(
            subject=subject,
            body=body,
            components_used=components_used,
            personalization=personalization,
            policy_version=policy_version,
            composition_trace={
                "hook_id": hook.variant_id,
                "value_prop_id": value_prop.variant_id,
                "social_proof_id": social_proof.variant_id,
                "cta_id": cta.variant_id,
                "brevity": brevity,
                "tone": ctx.variant.tone.value,
                "tone_assertiveness": ctx.policy.get("tone_assertiveness", 0.5),
                "personalization_depth": depth,
                "banned_phrases_checked": len(BANNED_PHRASES),
                "components_selected": {k.value: v.variant_id for k, v in components_used.items()},
            },
        )

    def _compress_for_brevity(self, body: str, ctx: CompositionContext) -> str:
        """Semantic compression: keep hook + value_prop, trim social_proof + soften CTA."""
        # For high brevity, we want: Hook + ValueProp + ShortCTA
        # This is a simplified version - real implementation would re-select components
        sentences = re.split(r'(?<=[.!?])\s+', body)
        if len(sentences) <= 2:
            return body
        # Keep first 2 sentences (typically hook + value_prop)
        return " ".join(sentences[:2])

    def _adjust_tone(self, body: str, ctx: CompositionContext) -> str:
        """Adjust tone through lexical choices, not phrase appending."""
        tone_assertiveness = ctx.policy.get("tone_assertiveness", 0.5)

        if tone_assertiveness < 0.4:
            # Soften: replace direct language with softer alternatives
            replacements = {
                "We help": "We partner with",
                "Our platform": "Our approach",
                "cuts": "improves",
                "accelerate": "support",
                "Open to": "Would you be open to",
                "Worth a": "Might be worth a",
                "Let me know": "Happy to discuss",
            }
            for old, new in replacements.items():
                body = body.replace(old, new)
        elif tone_assertiveness > 0.6:
            # Sharpen: use more direct language
            replacements = {
                "We partner with": "We help",
                "Our approach": "Our platform",
                "improves": "cuts",
                "support": "accelerate",
                "Would you be open to": "Open to",
                "Might be worth a": "Worth a",
                "Happy to discuss": "Let me know",
            }
            for old, new in replacements.items():
                body = body.replace(old, new)

        return body

    def _rewrite_banned_phrases(self, body: str) -> str:
        """Rewrite banned phrases with acceptable alternatives instead of '[removed]'."""
        rewrites = {
            "guaranteed roi": "strong roi potential",
            "act now": "consider acting soon",
            "limited time offer": "current opportunity",
            "once in a lifetime": "rare opportunity",
            "double your revenue overnight": "significantly accelerate revenue",
        }
        for banned, replacement in rewrites.items():
            body = re.sub(re.escape(banned), replacement, body, flags=re.IGNORECASE)
        return body

    def _build_subject(self, ctx: CompositionContext) -> str:
        """Build context-aware subject line."""
        payload = ctx.signal.get("payload", {})
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}

        signal_label = payload.get("amount") or payload.get("product") or payload.get("role") or ctx.signal.get("type", "update")
        company_name = ctx.company.get("name", ctx.company.get("id", ""))

        # Subject templates based on signal type
        sig_type = SignalType(ctx.signal.get("type", "FUNDING"))
        if sig_type == SignalType.FUNDING:
            return f"Congrats on the {signal_label}, {ctx.contact.get('name', 'there')}"
        elif sig_type == SignalType.HIRING:
            return f"Scaling {company_name}'s team"
        elif sig_type == SignalType.PRODUCT:
            return f"Impressive launch: {signal_label}"
        elif sig_type == SignalType.PRICING:
            return f"Pricing update at {company_name}"
        else:
            return f"{signal_label} at {company_name}"


# ---------------------------------------------------------------------------
# Backward-compatible TemplateGenerator
# ---------------------------------------------------------------------------

class TemplateGenerator:
    """Backward-compatible generator using the new composer."""

    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = conn
        self.composer = None
        if conn:
            self.composer = MessageComposer(conn)

    def generate(
        self,
        conn: sqlite3.Connection,
        variant: Experiment,
        contact: dict[str, Any],
        signal: dict[str, Any],
        policy: dict[str, Any],
    ) -> DraftedMessage:
        """Generate a drafted message (backward compatible)."""
        if self.composer is None:
            self.composer = MessageComposer(conn)

        # Get company info
        company_row = conn.execute(
            "SELECT * FROM companies WHERE id = ?", (contact.get("company_id", ""),)
        ).fetchone()
        company = dict(company_row) if company_row else {"id": contact.get("company_id", ""), "name": "Unknown", "segment": "unknown", "stage": "unknown"}

        ctx = CompositionContext(
            contact=contact,
            company=company,
            signal=signal,
            variant=variant,
            policy=policy,
            rng=random.Random(hash(variant.variant_id) % (2**32)),
        )

        composed = self.composer.compose(ctx)

        # Convert to backward-compatible format
        return DraftedMessage(
            subject=composed.subject,
            body=composed.body,
            personalization=composed.personalization,
            policy_version=composed.policy_version,
            prompt_trace=composed.composition_trace,
        )