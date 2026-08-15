"""Core enums for the gtm-loop domain (PLAN.md §3.3)."""

from enum import StrEnum


class SignalType(StrEnum):
    FUNDING = "FUNDING"
    HIRING = "HIRING"
    PRODUCT = "PRODUCT"
    PRICING = "PRICING"
    CONTENT = "CONTENT"


class ActionType(StrEnum):
    OUTREACH_EMAIL = "OUTREACH_EMAIL"
    LINKEDIN_CONNECT = "LINKEDIN_CONNECT"
    INTRO_REQUEST = "INTRO_REQUEST"
    FOLLOW_UP = "FOLLOW_UP"


class Channel(StrEnum):
    EMAIL = "EMAIL"
    LINKEDIN = "LINKEDIN"


class TimingSlot(StrEnum):
    MORNING = "MORNING"      # ~09:30 local
    MIDDAY = "MIDDAY"        # ~12:30 local
    AFTERNOON = "AFTERNOON"  # ~15:30 local


class ToneProfile(StrEnum):
    WARM = "WARM"
    DIRECT = "DIRECT"


class Mode(StrEnum):
    PROPOSE = "PROPOSE"
    AUTOPILOT = "AUTOPILOT"


class OpportunityStatus(StrEnum):
    QUALIFIED = "QUALIFIED"
    PLANNED = "PLANNED"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EDITED = "EDITED"
    SENT = "SENT"
    OUTCOME_RECORDED = "OUTCOME_RECORDED"
    LEARNING_APPLIED = "LEARNING_APPLIED"
    SKIPPED = "SKIPPED"
    DISMISSED = "DISMISSED"


class ActionStatus(StrEnum):
    PLANNED = "PLANNED"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EDITED = "EDITED"
    SENT = "SENT"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class OutcomeResult(StrEnum):
    REPLY = "REPLY"
    MEETING = "MEETING"
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"
    REJECTION = "REJECTION"
    UNSUB = "UNSUB"
    NO_RESPONSE = "NO_RESPONSE"


class RejectionReason(StrEnum):
    TOO_LONG = "too_long"
    TOO_SALESY = "too_salesy"
    MISSING_PERSONALIZATION = "missing_personalization"
    WRONG_CHANNEL = "wrong_channel"
    BAD_TIMING = "bad_timing"
    WRONG_TARGET = "wrong_target"


class Actor(StrEnum):
    AGENT = "agent"
    USER = "user"


class WarmthSignal(StrEnum):
    REPLIED = "replied"
    MET = "met"
    ENGAGED = "engaged"
    COLD = "cold"


class ActionClass(StrEnum):
    """Approval classification (PLAN.md §5.2)."""

    REVERSIBLE = "reversible"
    IRREVERSIBLE = "irreversible"
    EXTERNAL = "external"
    HIGH_COST = "high_cost"
