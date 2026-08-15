"""ACT: channel adapters (PLAN.md block 5).

Only simulated adapters exist in the scaffold; SIMULATION_MODE=on is enforced
at import time. Real adapters are intentionally absent (data-safety rule).
"""

from __future__ import annotations

import sqlite3

from src.config import SIMULATION_MODE
from src.domain.enums import ActionStatus


def _require_simulation() -> None:
    """Fail-fast guard: real send paths are prohibited."""
    if not SIMULATION_MODE:
        raise RuntimeError(
            "Real send adapters are not implemented. "
            "Set SIMULATION_MODE=on (default) to use simulated execution."
        )


def _update_action_status(conn: sqlite3.Connection, action_id: str, status: str) -> None:
    """Update the action row status in the database."""
    conn.execute(
        "UPDATE actions SET status = ? WHERE id = ?",
        (status, action_id),
    )
    conn.commit()


class EmailSim:
    """Simulated email adapter. No network calls."""

    @staticmethod
    def send(conn: sqlite3.Connection, action_id: str) -> ActionStatus:
        """Simulate sending an email. Returns SENT on success."""
        _require_simulation()
        _update_action_status(conn, action_id, ActionStatus.SENT)
        return ActionStatus.SENT


class LinkedinSim:
    """Simulated LinkedIn adapter. No network calls."""

    @staticmethod
    def send(conn: sqlite3.Connection, action_id: str) -> ActionStatus:
        """Simulate sending a LinkedIn request. Returns SENT on success."""
        _require_simulation()
        _update_action_status(conn, action_id, ActionStatus.SENT)
        return ActionStatus.SENT


# Channel → adapter mapping
ADAPTERS = {
    "EMAIL": EmailSim,
    "LINKEDIN": LinkedinSim,
}


def execute_action(conn: sqlite3.Connection, action_id: str, channel: str) -> ActionStatus:
    """Execute an action via the appropriate simulated adapter.

    Args:
        conn: Database connection.
        action_id: The action to execute.
        channel: Channel string (EMAIL or LINKEDIN).

    Returns:
        The resulting ActionStatus (always SENT in simulation).

    Raises:
        RuntimeError: If SIMULATION_MODE is off.
        ValueError: If channel has no adapter.
    """
    adapter = ADAPTERS.get(channel)
    if adapter is None:
        raise ValueError(f"No adapter for channel: {channel}")
    return adapter.send(conn, action_id)
