"""SQLite store: schema v1 + versioned migration runner (PLAN.md task A2).

SQLite is the single source of truth for gtm-loop:
companies, contacts, signals, opportunities, actions, outcomes, activity,
experiments (playbook variants), policies, warm_edges, memory_kv.

Design notes:
- WAL mode + foreign keys ON for every connection.
- `schema_version` table tracks applied migrations; `MIGRATIONS` is append-only.
- decision traces are stored as JSON blobs so explainability is replayable.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ..config import DB_PATH

SCHEMA_VERSION = 4

MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE companies (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        segment     TEXT NOT NULL,
        stage       TEXT NOT NULL,
        employees   INTEGER NOT NULL DEFAULT 0,
        tags        TEXT NOT NULL DEFAULT '[]'
    );

    CREATE TABLE contacts (
        id          TEXT PRIMARY KEY,
        company_id  TEXT NOT NULL REFERENCES companies(id),
        name        TEXT NOT NULL,
        title       TEXT NOT NULL,
        email       TEXT NOT NULL,
        linkedin    TEXT NOT NULL DEFAULT '',
        warmth      TEXT NOT NULL DEFAULT 'cold'
    );
    CREATE INDEX idx_contacts_company ON contacts(company_id);

    CREATE TABLE signals (
        id          TEXT PRIMARY KEY,
        company_id  TEXT NOT NULL REFERENCES companies(id),
        type        TEXT NOT NULL,
        payload     TEXT NOT NULL DEFAULT '{}',
        detected_at TEXT NOT NULL
    );
    CREATE INDEX idx_signals_company ON signals(company_id);
    CREATE INDEX idx_signals_detected ON signals(detected_at);

    CREATE TABLE opportunities (
        id          TEXT PRIMARY KEY,
        company_id  TEXT NOT NULL REFERENCES companies(id),
        signal_id   TEXT NOT NULL REFERENCES signals(id),
        status      TEXT NOT NULL DEFAULT 'QUALIFIED',
        score       REAL NOT NULL DEFAULT 0,
        fit_notes   TEXT NOT NULL DEFAULT '[]',
        decision_trace TEXT NOT NULL DEFAULT '{}',
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_opportunities_status ON opportunities(status);
    CREATE INDEX idx_opportunities_company ON opportunities(company_id);

    CREATE TABLE actions (
        id          TEXT PRIMARY KEY,
        opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
        contact_id  TEXT NOT NULL REFERENCES contacts(id),
        action_type TEXT NOT NULL,
        variant_id  TEXT NOT NULL,
        channel     TEXT NOT NULL,
        timing      TEXT NOT NULL,
        mode        TEXT NOT NULL,
        status      TEXT NOT NULL DEFAULT 'PLANNED',
        subject     TEXT NOT NULL DEFAULT '',
        body        TEXT NOT NULL DEFAULT '',
        decision_trace TEXT NOT NULL DEFAULT '{}',
        guardrail_blocks TEXT NOT NULL DEFAULT '[]',
        cost_units  INTEGER NOT NULL DEFAULT 0,
        policy_version INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_actions_status ON actions(status);
    CREATE INDEX idx_actions_opportunity ON actions(opportunity_id);

    CREATE TABLE outcomes (
        id          TEXT PRIMARY KEY,
        action_id   TEXT NOT NULL REFERENCES actions(id),
        result      TEXT NOT NULL,
        detail      TEXT NOT NULL DEFAULT '',
        at          TEXT NOT NULL
    );
    CREATE INDEX idx_outcomes_action ON outcomes(action_id);

    CREATE TABLE activity (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        at          TEXT NOT NULL DEFAULT (datetime('now')),
        actor       TEXT NOT NULL,
        action_id   TEXT REFERENCES actions(id),
        event       TEXT NOT NULL,
        status      TEXT NOT NULL DEFAULT '',
        outcome     TEXT NOT NULL DEFAULT '',
        reason      TEXT NOT NULL DEFAULT '',
        policy_version INTEGER NOT NULL DEFAULT 0,
        detail      TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX idx_activity_at ON activity(at);

    CREATE TABLE experiments (
        variant_id      TEXT PRIMARY KEY,
        segment         TEXT NOT NULL,
        template        TEXT NOT NULL,
        channel         TEXT NOT NULL,
        timing          TEXT NOT NULL,
        tone            TEXT NOT NULL,
        personalization_depth INTEGER NOT NULL DEFAULT 1,
        stats           TEXT NOT NULL DEFAULT '{}'  -- {"sent":0,"replies":0,"meetings":0,...}
    );

    CREATE TABLE policies (
        version     INTEGER PRIMARY KEY,
        policy      TEXT NOT NULL,          -- JSON: brevity, tone_assertiveness, ...
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        source      TEXT NOT NULL DEFAULT 'initial'
    );

    CREATE TABLE warm_edges (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        contact_a   TEXT NOT NULL REFERENCES contacts(id),
        contact_b   TEXT NOT NULL REFERENCES contacts(id),
        strength    REAL NOT NULL DEFAULT 0.0,
        direction   TEXT NOT NULL DEFAULT 'mutual',
        last_interaction TEXT NOT NULL DEFAULT '',
        source      TEXT NOT NULL DEFAULT '',
        UNIQUE(contact_a, contact_b)
    );
    CREATE INDEX idx_warm_edges_a ON warm_edges(contact_a);
    CREATE INDEX idx_warm_edges_b ON warm_edges(contact_b);

    CREATE TABLE memory_kv (
        key         TEXT PRIMARY KEY,
        namespace   TEXT NOT NULL DEFAULT 'general',
        value       TEXT NOT NULL,
        updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_memory_ns ON memory_kv(namespace);
    """,
    # --- Migration v2: add segment, expected_effect, confidence to actions -----
    2: """
    ALTER TABLE actions ADD COLUMN segment TEXT NOT NULL DEFAULT '';
    ALTER TABLE actions ADD COLUMN expected_effect TEXT NOT NULL DEFAULT '';
    ALTER TABLE actions ADD COLUMN confidence REAL NOT NULL DEFAULT 0.0;
    """,
    # --- Migration v3: revenue attribution (Issue #45) -------------------------
    # Opportunities can be marked WON with a simulated ARR from segment priors.
    3: """
    ALTER TABLE opportunities ADD COLUMN won_at TEXT NOT NULL DEFAULT '';
    ALTER TABLE opportunities ADD COLUMN arr REAL NOT NULL DEFAULT 0.0;
    ALTER TABLE opportunities ADD COLUMN pipeline_stage TEXT NOT NULL DEFAULT 'QUALIFIED';
    """,
    # --- Migration v4: multi-touch sequences (Issue #44) -----------------------
    # Sequences = ordered steps with delay windows; actions link to a sequence.
    4: """
    CREATE TABLE sequences (
        sequence_id TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        segment     TEXT NOT NULL DEFAULT '',
        stats       TEXT NOT NULL DEFAULT '{}',
        max_steps   INTEGER NOT NULL DEFAULT 3,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE sequence_steps (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        sequence_id TEXT NOT NULL REFERENCES sequences(sequence_id),
        step_order  INTEGER NOT NULL,
        action_type TEXT NOT NULL,
        channel     TEXT NOT NULL,
        delay_days  INTEGER NOT NULL DEFAULT 3,
        content_hint TEXT NOT NULL DEFAULT ''
    );
    ALTER TABLE actions ADD COLUMN sequence_id TEXT NOT NULL DEFAULT '';
    ALTER TABLE actions ADD COLUMN step_index INTEGER NOT NULL DEFAULT 0;
    """,
}


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open a connection with WAL + FK enforcement; applies migrations."""
    db_path = Path(path) if path else Path(DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


@contextmanager
def get_connection(path: str | Path | None = None):
    """Context manager that yields a connection with automatic cleanup."""
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def migrate(conn: sqlite3.Connection) -> None:
    """Apply pending migrations in order (append-only MIGRATIONS dict)."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
    )
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    current = row["v"] if row and row["v"] is not None else 0
    for version in sorted(MIGRATIONS):
        if version > current:
            conn.executescript(MIGRATIONS[version])
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    conn.commit()


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return row["v"] if row and row["v"] is not None else 0


# --------------------------------------------------------------------------- helpers
_ALLOWED_TABLES = {
    "companies", "contacts", "signals", "opportunities", "actions",
    "outcomes", "activity", "experiments", "policies", "warm_edges",
    "memory_kv", "schema_version",
}
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def insert_json(conn: sqlite3.Connection, table: str, row: dict) -> None:
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Unknown table: {table}")
    cols = [c for c in row.keys() if _IDENTIFIER_RE.match(c)]
    if not cols:
        raise ValueError("No valid column names in row")
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
    conn.execute(sql, [json.dumps(v) if isinstance(v, (dict, list)) else v for v in [row[c] for c in cols]])
