"""Pydantic contracts for the gtm-loop pipeline (PLAN.md §3.3).

These are the stable interface between engine stages. Keeping them as plain
pydantic models (no ORM) keeps the store layer free to evolve.
"""

from __future__ import annotations
from enum import Enum

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from .enums import (
    ActionClass,
    ActionType,
    Channel,
    Mode,
    OpportunityStatus,
    OutcomeResult,
    SignalType,
    TimingSlot,
    ToneProfile,
    WarmthSignal,
)


# --------------------------------------------------------------------------- SENSE
class Signal(BaseModel):
    id: str
    company_id: str
    type: SignalType
    payload: dict[str, Any]
    detected_at: datetime


class Qualification(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    fit_notes: list[str] = Field(default_factory=list)
    icp_hits: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- DECIDE
class Experiment(BaseModel):
    """A playbook variant: template x channel x timing x tone x segment."""

    variant_id: str
    segment: str
    template: str
    channel: Channel
    timing: TimingSlot
    tone: ToneProfile
    personalization_depth: int = Field(ge=0, le=5)
    stats: dict[str, int] = Field(default_factory=dict)  # sent, replies, meetings, ...


class PlannedAction(BaseModel):
    action_type: ActionType
    variant_id: str
    channel: Channel
    timing: TimingSlot
    segment: str
    expected_effect: str
    confidence: float = Field(ge=0.0, le=1.0)


# --------------------------------------------------------------------------- GENERATE


class ComponentType(str, Enum):
    """Types of message components."""
    HOOK = "hook"
    VALUE_PROP = "value_prop"
    SOCIAL_PROOF = "social_proof"
    CTA = "cta"


class ComponentVariant(BaseModel):
    """A single variant of a message component."""
    component_type: ComponentType
    variant_id: str
    text: str
    # Conditions for when this variant applies
    roles: list[str] = Field(default_factory=list)  # e.g. ["CEO", "VP Sales"]
    segments: list[str] = Field(default_factory=list)  # e.g. ["saas-b2b", "fintech"]
    stages: list[str] = Field(default_factory=list)  # e.g. ["seed", "series-a"]
    signals: list[str] = Field(default_factory=list)  # e.g. ["FUNDING", "HIRING"]
    tone_profiles: list[str] = Field(default_factory=list)  # e.g. ["WARM", "DIRECT"]
    weight: float = Field(default=1.0, ge=0.0)  # Selection weight
    metadata: dict[str, Any] = Field(default_factory=dict)


class ComponentLibrary(BaseModel):
    """Library of all component variants organized by type."""
    hooks: list[ComponentVariant] = Field(default_factory=list)
    value_props: list[ComponentVariant] = Field(default_factory=list)
    social_proofs: list[ComponentVariant] = Field(default_factory=list)
    ctas: list[ComponentVariant] = Field(default_factory=list)

    def get_variants(self, component_type: ComponentType) -> list[ComponentVariant]:
        return getattr(self, f"{component_type.value}s", [])


class ComposedMessage(BaseModel):
    """A fully composed message with selected components."""
    subject: str
    body: str
    components_used: dict[ComponentType, ComponentVariant]
    personalization: list[str] = Field(default_factory=list)
    policy_version: int
    composition_trace: dict[str, Any] = Field(default_factory=dict)


class DraftedMessage(BaseModel):
    """Backward-compatible drafted message (for API compatibility)."""
    subject: str
    body: str
    personalization: list[str] = Field(default_factory=list)
    policy_version: int
    prompt_trace: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- PROPOSE / PERMISSION
class PermissionDecision(BaseModel):
    mode: Mode
    requires_approval: bool
    reasons: list[str] = Field(default_factory=list)
    guardrail_blocks: list[str] = Field(default_factory=list)
    action_class: ActionClass = ActionClass.REVERSIBLE


class DecisionCard(BaseModel):
    """The explainability payload rendered by the UI (PLAN.md §6)."""

    action_id: str
    action_type: ActionType
    target: str
    channel: Channel
    timing: TimingSlot
    cost_units: int
    why: list[str]
    evidence: list[str]
    guardrails: list[str]
    learned: list[str]
    next_steps: str
    expected_effect: str


# --------------------------------------------------------------------------- OBSERVE
class Outcome(BaseModel):
    action_id: str
    result: OutcomeResult
    detail: str = ""
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# --------------------------------------------------------------------------- LEARN
class PolicyDelta(BaseModel):
    field: str
    delta: float
    source: str  # e.g. "user_rejection:too_salesy" or "user_edit"


class EdgeDelta(BaseModel):
    contact_a: str
    contact_b: str
    strength_delta: float
    source: str


class LearningDelta(BaseModel):
    variant_updates: dict[str, dict[str, int]] = Field(default_factory=dict)
    policy_deltas: list[PolicyDelta] = Field(default_factory=list)
    warm_graph_deltas: list[EdgeDelta] = Field(default_factory=list)
    playbook_new_version: int = 0


# --------------------------------------------------------------------------- CORE ENTITIES
class Company(BaseModel):
    id: str
    name: str
    segment: str
    stage: str
    employees: int
    tags: list[str] = Field(default_factory=list)


class Contact(BaseModel):
    id: str
    company_id: str
    name: str
    title: str
    email: str
    linkedin: str
    warmth: WarmthSignal = WarmthSignal.COLD


class Opportunity(BaseModel):
    id: str
    company_id: str
    signal_id: str
    status: OpportunityStatus = OpportunityStatus.QUALIFIED
    score: float = 0.0
    fit_notes: list[str] = Field(default_factory=list)
    decision_trace: dict[str, Any] = Field(default_factory=dict)