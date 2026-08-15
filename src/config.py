"""Runtime configuration: budgets, caps, guardrails, thresholds (PLAN.md §5.3).

All values are plain module constants so the guardrail engine is trivially
inspectable and explainable. Env overrides are applied at import time.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid value for %s: %r — using default %d", name, raw, default)
        return default


# --- qualification ---------------------------------------------------------
QUALIFY_THRESHOLD: float = 0.6
SIGNAL_DEDUPE_WINDOW_HOURS: int = 24

# --- scoring weights --------------------------------------------------------
SIGNAL_TYPE_WEIGHTS: dict[str, float] = {
    "FUNDING": 0.9,
    "HIRING": 0.7,
    "PRODUCT": 0.6,
    "PRICING": 0.5,
    "CONTENT": 0.3,
}

STAGE_WEIGHTS: dict[str, float] = {
    "seed": 0.8,
    "series-a": 0.9,
    "series-b": 0.7,
    "growth": 0.6,
    "late": 0.4,
}

TARGET_SEGMENTS: set[str] = {"saas-b2b", "developer-tools", "fintech", "ai", "infra", "security"}

EMPLOYEE_BRACKETS: list[tuple[int, int, float]] = [
    (0, 20, 0.4),
    (20, 100, 0.9),
    (100, 500, 0.7),
    (500, 10_000, 0.5),
    (10_000, 100_000, 0.3),
]

# --- signal generation probabilities ----------------------------------------
SIGNAL_PROB_FUNDING: float = 0.7
SIGNAL_PROB_PRODUCT: float = 0.5
SIGNAL_PROB_HIRING: float = 0.4
HIRING_EMPLOYEE_THRESHOLD: int = 50

INTERESTING_TAGS: set[str] = {"funding", "seed-funded", "v2", "expansion", "zero-trust", "research"}

# --- budgets & rate caps ----------------------------------------------------
DAILY_SEND_BUDGET: int = _env_int("GTM_DAILY_SEND_BUDGET", 20)
WEEKLY_SEND_BUDGET: int = _env_int("GTM_WEEKLY_SEND_BUDGET", 100)
MAX_SENDS_PER_CONTACT_PER_DAY: int = 1
MAX_FOLLOW_UPS_PER_THREAD: int = 3
MIN_INTERVAL_BETWEEN_CONTACT_ACTIONS_HOURS: int = 24
COST_UNITS_PER_SEND: int = 1
HIGH_COST_THRESHOLD_UNITS: int = 10  # per action, above this => HIGH_COST class

# --- guardrail content -------------------------------------------------------
BANNED_PHRASES: tuple[str, ...] = (
    "guaranteed roi",
    "act now",
    "limited time offer",
    "once in a lifetime",
    "double your revenue overnight",
)
# Minimal PII scrub check (demo-grade; not a security boundary)
PII_PATTERNS: tuple[str, ...] = ("password", "social security", "credit card")

# --- simulated revenue model (D1: no real money) -----------------------------
# Segment → expected annual recurring revenue (ARR) for a WON opportunity.
DEAL_SIZES: dict[str, int] = {
    "saas-b2b": 12000,
    "developer-tools": 18000,
    "fintech": 25000,
    "healthtech": 20000,
    "ecommerce": 8000,
    "ai-native": 15000,
}

# --- autopilot scope (defaults; user-editable at runtime) --------------------
AUTOPILOT_DEFAULT_SCOPE: dict = {
    "enabled": False,  # Propose mode is the default (PLAN.md §5.1)
    "allowed_segments": [],
    "allowed_channels": [],
    "max_sends_per_day": 10,
    "max_cost_units_per_action": 3,
    "allowed_timing": [],
}

# --- simulation --------------------------------------------------------------
SIMULATION_MODE: bool = os.environ.get("SIMULATION_MODE", "on").lower() in ("1", "true", "on", "yes")
LLM_BASE_URL: str | None = os.environ.get("LLM_BASE_URL")
LLM_MODEL: str | None = os.environ.get("LLM_MODEL")

# --- real channel integrations (Issue #43, P2-4) -----------------------------
# Real adapters are gated behind SIMULATION_MODE=off + provider config.
# Email (SMTP):
SMTP_HOST: str | None = os.environ.get("SMTP_HOST")
SMTP_PORT: int | None = _env_int("SMTP_PORT", 587)
SMTP_USERNAME: str | None = os.environ.get("SMTP_USERNAME")
SMTP_PASSWORD: str | None = os.environ.get("SMTP_PASSWORD")
SMTP_FROM: str | None = os.environ.get("SMTP_FROM")
# Slack operator notifications (telemetry-only):
SLACK_WEBHOOK_URL: str | None = os.environ.get("SLACK_WEBHOOK_URL")
# Webhook bus (comma-separated endpoints, e.g. n8n/Zapier):
WEBHOOK_ENDPOINTS: tuple[str, ...] = tuple(
    u.strip() for u in os.environ.get("WEBHOOK_ENDPOINTS", "").split(",") if u.strip()
)


class SecretStr:
    """String that masks its value in repr/log output to prevent key exposure."""

    __slots__ = ("_value",)

    def __init__(self, value: str | None):
        self._value = value

    def __repr__(self) -> str:
        return "***" if self._value else "None"

    def __str__(self) -> str:
        return self._value or ""

    def __bool__(self) -> bool:
        return self._value is not None

    @property
    def value(self) -> str | None:
        return self._value


LLM_API_KEY: SecretStr = SecretStr(os.environ.get("LLM_API_KEY"))

# --- API auth ----------------------------------------------------------------
# When set, all /api/v1 endpoints require the key via the X-API-Key header.
# When unset (default), endpoints are open for local development.
GTM_API_KEY: SecretStr = SecretStr(os.environ.get("GTM_API_KEY"))

# --- scheduler ----------------------------------------------------------------
HEARTBEAT_INTERVAL_SECONDS: int = _env_int("HEARTBEAT_INTERVAL_SECONDS", 300)

# --- store --------------------------------------------------------------------
DB_PATH: str = os.environ.get("GTM_DB_PATH", "gtm-loop.db")
