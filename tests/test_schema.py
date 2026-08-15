"""Schema + seed smoke tests (PLAN.md task A4)."""

import sqlite3

import pytest

from seed_data import seed
from src.store.db import SCHEMA_VERSION, connect, current_version


@pytest.fixture()
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    yield conn
    conn.close()


def test_migrations_apply(db):
    assert current_version(db) == SCHEMA_VERSION


def test_all_domain_tables_exist(db):
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    tables = {r["name"] for r in rows}
    for expected in (
        "companies", "contacts", "signals", "opportunities", "actions",
        "outcomes", "activity", "experiments", "policies", "warm_edges", "memory_kv",
    ):
        assert expected in tables


def test_seed_is_deterministic_and_complete(tmp_path):
    conn1 = connect(tmp_path / "a.db")
    seed(conn1, reset=True)
    conn2 = connect(tmp_path / "b.db")
    seed(conn2, reset=True)

    for table in ("companies", "contacts", "warm_edges", "experiments"):
        a = conn1.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        b = conn2.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        assert a == b > 0

    conn1.close()
    conn2.close()


def test_foreign_keys_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO contacts (id, company_id, name, title, email) VALUES ('x','missing','N','T','e')")
        db.commit()


def test_seed_creates_initial_policy_and_variants(db):
    seed(db, reset=True)
    n_policies = db.execute("SELECT COUNT(*) AS n FROM policies").fetchone()["n"]
    n_variants = db.execute("SELECT COUNT(*) AS n FROM experiments").fetchone()["n"]
    assert n_policies == 1
    assert n_variants >= 8


def test_warm_edges_have_valid_contacts(db):
    seed(db, reset=True)
    rows = db.execute(
        """SELECT we.contact_a, we.contact_b FROM warm_edges we
           LEFT JOIN contacts c ON c.id = we.contact_a
           WHERE c.id IS NULL"""
    ).fetchall()
    assert rows == []
