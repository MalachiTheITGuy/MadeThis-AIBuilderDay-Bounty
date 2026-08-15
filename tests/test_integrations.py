"""Tests for real channel adapters behind the simulation rail (Issue #43, P2-4)."""

import pytest

from src.engine.integrations import (
    EmailAdapter,
    IntegrationError,
    SlackAdapter,
    WebhookBus,
    build_real_adapters,
)


class _FakeConn:
    """Minimal fake connection with an actions table."""

    def __init__(self, actions=None, contacts=None):
        self.actions = actions or {}
        self.contacts = contacts or {}
        self.updated = []

    def execute(self, sql, params=()):
        if sql.strip().upper().startswith("UPDATE ACTIONS"):
            self.updated.append(params)
            return _FakeCursor()
        if "FROM actions" in sql and "contact_id" in sql:
            a = self.actions.get(params[0])
            return _FakeCursor(a)
        if "FROM contacts" in sql:
            c = self.contacts.get(params[0])
            return _FakeCursor(c)
        return _FakeCursor(None)

    def commit(self):
        pass


class _FakeCursor:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


def _configure(monkeypatch, **env):
    import src.engine.integrations as mod
    for key in ("SIMULATION_MODE", "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME",
                "SMTP_PASSWORD", "SMTP_FROM", "SLACK_WEBHOOK_URL", "WEBHOOK_ENDPOINTS"):
        monkeypatch.setattr(mod, key, env.get(key, ""))
    monkeypatch.setattr(mod, "LLM_API_KEY", None)
    return mod


def test_adapters_rejected_in_simulation_mode(monkeypatch):
    mod = _configure(monkeypatch, SIMULATION_MODE=True, SMTP_HOST="smtp.example.com")
    with pytest.raises(IntegrationError):
        EmailAdapter()
    with pytest.raises(IntegrationError):
        SlackAdapter()
    with pytest.raises(IntegrationError):
        WebhookBus()


def test_email_adapter_requires_host(monkeypatch):
    mod = _configure(monkeypatch, SIMULATION_MODE=False, SMTP_HOST="")
    with pytest.raises(IntegrationError, match="SMTP_HOST"):
        EmailAdapter()


def test_email_adapter_requires_from(monkeypatch):
    mod = _configure(monkeypatch, SIMULATION_MODE=False, SMTP_HOST="smtp.example.com")
    with pytest.raises(IntegrationError, match="SMTP_FROM"):
        EmailAdapter()


def test_email_adapter_send_missing_action(monkeypatch):
    mod = _configure(monkeypatch, SIMULATION_MODE=False, SMTP_HOST="h", SMTP_FROM="a@b.com")
    adapter = EmailAdapter()
    conn = _FakeConn()
    with pytest.raises(IntegrationError, match="Action not found"):
        adapter.send(conn, "nope")


def test_email_adapter_send_no_contact_email(monkeypatch):
    mod = _configure(monkeypatch, SIMULATION_MODE=False, SMTP_HOST="h", SMTP_FROM="a@b.com")
    adapter = EmailAdapter()
    conn = _FakeConn(
        actions={"a1": {"subject": "Hi", "body": "Hello", "contact_id": "c1"}},
        contacts={"c1": {"email": ""}},
    )
    with pytest.raises(IntegrationError, match="no email"):
        adapter.send(conn, "a1")


def test_email_adapter_send_smtp_failure_raises(monkeypatch):
    mod = _configure(monkeypatch, SIMULATION_MODE=False, SMTP_HOST="h", SMTP_FROM="a@b.com")
    adapter = EmailAdapter()
    conn = _FakeConn(
        actions={"a1": {"subject": "Hi", "body": "Hello", "contact_id": "c1"}},
        contacts={"c1": {"email": "to@example.com"}},
    )
    # SMTP to a non-resolvable host → connection error, surfaced as IntegrationError
    with pytest.raises(IntegrationError):
        adapter.send(conn, "a1")


def test_slack_adapter_requires_webhook(monkeypatch):
    mod = _configure(monkeypatch, SIMULATION_MODE=False, SLACK_WEBHOOK_URL="")
    with pytest.raises(IntegrationError, match="SLACK_WEBHOOK_URL"):
        SlackAdapter()


def test_webhook_bus_requires_endpoints(monkeypatch):
    mod = _configure(monkeypatch, SIMULATION_MODE=False, WEBHOOK_ENDPOINTS=())
    bus = WebhookBus()
    with pytest.raises(IntegrationError, match="WEBHOOK_ENDPOINTS"):
        bus.emit("outcome", {})


def test_build_real_adapters_empty_in_simulation(monkeypatch):
    mod = _configure(monkeypatch, SIMULATION_MODE=True, SMTP_HOST="h", SLACK_WEBHOOK_URL="u", WEBHOOK_ENDPOINTS=("u",))
    assert build_real_adapters() == {}


def test_build_real_adapters_partial_config_never_silent(monkeypatch):
    # SMTP configured but no Slack/webhook → only email adapter built
    mod = _configure(monkeypatch, SIMULATION_MODE=False, SMTP_HOST="h", SMTP_FROM="a@b.com")
    adapters = build_real_adapters()
    assert set(adapters) == {"EMAIL"}
