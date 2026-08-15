"""Real channel adapters behind the simulation rail (Issue #43, P2-4).

Simulation stays the default (`SIMULATION_MODE=on`, data-safety rule D1).
Real adapters are only constructible when:
  1. `SIMULATION_MODE=off`, AND
  2. the required provider config is present.

All real sends carry `ActionClass.EXTERNAL` → they must go through
`permission.evaluate` which always requires human approval, so autopilot can
never auto-fire a real send. Webhooks are telemetry-only (no sending surface).
"""

from __future__ import annotations

import json
import logging
import smtplib
import ssl
import urllib.error
import urllib.request
from email.mime.text import MIMEText
from typing import Callable

from src.config import (
    LLM_API_KEY,
    SIMULATION_MODE,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    SLACK_WEBHOOK_URL,
    WEBHOOK_ENDPOINTS,
)
from src.domain.enums import ActionStatus

logger = logging.getLogger("gtm-loop")

SendFn = Callable[[object, str], ActionStatus]


class IntegrationError(RuntimeError):
    """Raised when a real adapter cannot be constructed or fails to send."""


def _require_real_mode(provider: str) -> None:
    """Fail fast: real adapters cannot be built in simulation mode."""
    if SIMULATION_MODE:
        raise IntegrationError(
            f"Cannot construct {provider}: SIMULATION_MODE is on. "
            "Real sends are disabled for data safety."
        )


def _require(env_value: str | None, name: str, provider: str) -> str:
    if not env_value:
        raise IntegrationError(
            f"Cannot construct {provider}: {name} is not configured. "
            "No real send path will be used."
        )
    return env_value


# ---------------------------------------------------------------------------
# Email adapter (SMTP)
# ---------------------------------------------------------------------------

class EmailAdapter:
    """Real SMTP email adapter. Requires SMTP_* env config + SIMULATION_MODE=off."""

    def __init__(self) -> None:
        _require_real_mode("EmailAdapter")
        self.host = _require(SMTP_HOST, "SMTP_HOST", "EmailAdapter")
        self.port = SMTP_PORT or 587
        self.username = SMTP_USERNAME or ""
        self.password = SMTP_PASSWORD or ""
        self.from_addr = SMTP_FROM or self.username
        if not self.from_addr:
            raise IntegrationError(
                "Cannot construct EmailAdapter: SMTP_FROM or SMTP_USERNAME required."
            )

    def send(self, conn: object, action_id: str) -> ActionStatus:
        """Fetch the drafted action and deliver it over SMTP."""
        row = conn.execute(
            "SELECT subject, body, contact_id FROM actions WHERE id = ?",
            (action_id,),
        ).fetchone()
        if row is None:
            raise IntegrationError(f"Action not found: {action_id}")
        to_addr = conn.execute(
            "SELECT email FROM contacts WHERE id = ?", (row["contact_id"],)
        ).fetchone()
        if to_addr is None or not to_addr["email"]:
            raise IntegrationError(
                f"Contact {row['contact_id']} has no email; cannot deliver."
            )

        msg = MIMEText(row["body"] or "")
        msg["Subject"] = row["subject"] or ""
        msg["From"] = self.from_addr
        msg["To"] = to_addr["email"]

        context = ssl.create_default_context()
        try:
            with smtplib.SMTP(self.host, self.port, timeout=15) as server:
                server.starttls(context=context)
                if self.username:
                    server.login(self.username, self.password)
                server.send_message(msg)
        except Exception as exc:  # network/auth errors — never silently drop
            raise IntegrationError(f"SMTP send failed for {action_id}: {exc}") from exc

        conn.execute(
            "UPDATE actions SET status = ? WHERE id = ?",
            (ActionStatus.SENT, action_id),
        )
        conn.commit()
        return ActionStatus.SENT


# ---------------------------------------------------------------------------
# Slack notifications (telemetry-only)
# ---------------------------------------------------------------------------

class SlackAdapter:
    """Posts operator notifications to a Slack webhook. Telemetry only — no new
    sending surface for prospects."""

    def __init__(self) -> None:
        _require_real_mode("SlackAdapter")
        self.url = _require(SLACK_WEBHOOK_URL, "SLACK_WEBHOOK_URL", "SlackAdapter")

    def notify(self, text: str) -> bool:
        payload = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError) as exc:
            logger.warning("Slack notify failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Webhook bus (integration story — decision/outcome/learning events)
# ---------------------------------------------------------------------------

class WebhookBus:
    """POSTs JSON events to configured endpoints (n8n/Zapier/etc.)."""

    def __init__(self) -> None:
        _require_real_mode("WebhookBus")
        self.endpoints = WEBHOOK_ENDPOINTS

    def emit(self, event: str, data: dict) -> int:
        """Emit an event to every configured endpoint. Returns number delivered."""
        if not self.endpoints:
            raise IntegrationError(
                "Cannot emit webhook event: WEBHOOK_ENDPOINTS is empty."
            )
        delivered = 0
        body = json.dumps({"event": event, "data": data}).encode("utf-8")
        for url in self.endpoints:
            req = urllib.request.Request(
                url, data=body, headers={"Content-Type": "application/json"}
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status in (200, 201, 202, 204):
                        delivered += 1
            except (urllib.error.URLError, OSError) as exc:
                logger.warning("Webhook %s failed: %s", url, exc)
        return delivered


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_real_adapters() -> dict:
    """Construct all configured real adapters.

    In simulation mode, always returns {} (no real path is ever reachable).
    When SIMULATION_MODE=off, raises IntegrationError if required config is
    missing for a provider. Never partially returns.
    """
    if SIMULATION_MODE:
        return {}
    adapters: dict = {}
    if SMTP_HOST:
        adapters["EMAIL"] = EmailAdapter()
    if SLACK_WEBHOOK_URL:
        adapters["SLACK"] = SlackAdapter()
    if WEBHOOK_ENDPOINTS:
        adapters["WEBHOOK"] = WebhookBus()
    return adapters
