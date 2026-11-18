"""The one-time copy of an old SQLite orderplan.db (version 8) into PostgreSQL (app/copy_from_sqlite.py)."""
import sqlite3
from contextlib import closing

import pytest

from app.copy_from_sqlite import copy
from app.repository import Repository
from tests.test_repository import S, _build_run, _stock

# The SQLite layout at version 8, as the last SQLite version of the tool left it (columns in the order the
# upgrades added them).
V8_SQLITE = """
CREATE TABLE supplier_settings (supplier TEXT PRIMARY KEY, holding_months REAL NULL, updated_at TEXT NOT NULL,
    moq REAL NOT NULL DEFAULT 0, lead_time_days INTEGER NULL, order_cycle_months INTEGER NOT NULL DEFAULT 1,
    order_cycle_weeks INTEGER NOT NULL DEFAULT 4, holding_days REAL NULL);
CREATE TABLE settings_log (id INTEGER PRIMARY KEY AUTOINCREMENT, supplier TEXT NOT NULL, old_value REAL NULL,
    new_value REAL NULL, changed_at TEXT NOT NULL, field TEXT NOT NULL DEFAULT 'holding_months');
CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, file_name TEXT NOT NULL,
    sales_file_name TEXT NOT NULL, plan_date TEXT NOT NULL, sku_count INTEGER NOT NULL, parsed_json TEXT NOT NULL,
    actual_json TEXT NOT NULL, result_json TEXT NOT NULL, pg_file_name TEXT NULL, pdg_file_name TEXT NULL,
    stock_json TEXT NULL, sit_file_name TEXT NULL);
"""


def _sqlite_file(path, version=8):
    parsed, actual, result = _build_run()
    with closing(sqlite3.connect(path)) as c:
        c.executescript(V8_SQLITE)
        c.execute("INSERT INTO supplier_settings VALUES ('A', 2.5, '2026-10-01T00:00:00', 8000, 14, 1, 3, 75)")
        c.execute("INSERT INTO settings_log VALUES (5, 'A', NULL, 2.5, '2026-10-01T00:00:00', 'holding_months')")
        c.execute("INSERT INTO settings_log VALUES (7, 'A', NULL, 75, '2026-11-01T00:00:00', 'holding_days')")
        c.execute("INSERT INTO runs VALUES (3, '2026-11-02T09:00:00', 'in.xlsx', 's.xlsx', ?, 1, ?, ?, ?,"
                  " 'p.xlsx', 'd.xlsx', ?, 't.xlsx')",
                  (result.plan_date.isoformat(), parsed.model_dump_json(), actual.model_dump_json(),
                   result.model_dump_json(), _stock().model_dump_json()))
        c.execute(f"PRAGMA user_version = {version}")
        c.commit()
    return parsed, actual, result


def test_copy_keeps_every_row_and_ids_continue(db, tmp_path):
    parsed, actual, result = _sqlite_file(tmp_path / "orderplan.db")
    assert copy(tmp_path / "orderplan.db", **db) == {"supplier_settings": (1, 1), "settings_log": (2, 2), "runs": (1, 1)}
    repo = Repository(**db)
    assert repo.get_settings() == {"A": S("A", 75, 8000, 14, cycle=3)}
    assert [(e.id, e.field) for e in repo.get_settings_log()] == [(7, "holding_days"), (5, "holding_months")]
    run = repo.get_run(3)
    assert run.parsed == parsed and run.actual == actual and run.result == result and run.stock == _stock()
    assert run.sit_file_name == "t.xlsx"
    # new rows get IDs after the copied ones
    assert [e.id for e in repo.save_settings([S("A", 80, 8000, 14, cycle=3)])] == [8]
    assert repo.create_run("n.xlsx", "s.xlsx", "p.xlsx", "d.xlsx", "t.xlsx", parsed, actual, _stock(), result) == 4


def test_copy_refuses_a_database_with_data(db, tmp_path):
    _sqlite_file(tmp_path / "orderplan.db")
    copy(tmp_path / "orderplan.db", **db)
    with pytest.raises(SystemExit, match="already has data"):
        copy(tmp_path / "orderplan.db", **db)
    assert len(Repository(**db).get_settings_log()) == 2   # nothing added by the refused copy


def test_copy_refuses_an_old_file_version(db, tmp_path):
    _sqlite_file(tmp_path / "old.db", version=7)
    with pytest.raises(SystemExit, match="version 7"):
        copy(tmp_path / "old.db", **db)
    assert Repository(**db).get_settings() == {}
