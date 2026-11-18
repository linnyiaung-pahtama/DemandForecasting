"""Tests use a PostgreSQL test database, never the planner's real one: each test that needs storage gets its own
throwaway schema there (the `db` fixture), dropped afterwards.

Set TEST_DATABASE_URL, e.g. postgresql://127.0.0.1:5432/orderplan_test, plus TEST_DATABASE_USER /
TEST_DATABASE_PASSWORD when the URL has no user (or put them in backend/.env.pgtest, which git ignores).
Tests that need no database run without it.
"""
import os
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values

_local = dotenv_values(Path(__file__).resolve().parent.parent / ".env.pgtest")
TEST_URL = os.environ.get("TEST_DATABASE_URL") or _local.get("TEST_DATABASE_URL")
# Set before any `app` module is imported, so app.config can only ever see the test database.
os.environ["DATABASE_URL"] = TEST_URL or "postgresql://test-database-not-configured.invalid/none"
os.environ["DATABASE_USER"] = os.environ.get("TEST_DATABASE_USER") or _local.get("TEST_DATABASE_USER") or ""
os.environ["DATABASE_PASSWORD"] = os.environ.get("TEST_DATABASE_PASSWORD") or _local.get("TEST_DATABASE_PASSWORD") or ""


@pytest.fixture
def db():
    """A fresh, empty schema in the test database, as keyword arguments for Repository / create_app / connect."""
    if not TEST_URL:
        pytest.fail("No test database: set TEST_DATABASE_URL (see README, Tests).")
    from app.db import connect
    schema = f"t_{uuid.uuid4().hex[:12]}"
    with connect(TEST_URL) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    yield {"database_url": TEST_URL, "schema": schema}
    with connect(TEST_URL) as conn:
        conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.fixture
def db_conn(db):
    """A direct connection to the test's schema, for tests that edit stored rows. Commit before calling the app."""
    from app.db import connect
    with connect(**db) as conn:
        yield conn
