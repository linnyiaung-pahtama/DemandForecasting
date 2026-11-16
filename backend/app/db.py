import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 8
V1_BACKUP_NAME = "orderplan.v1-backup"

SCHEMA = """
CREATE TABLE IF NOT EXISTS supplier_settings (
    supplier TEXT PRIMARY KEY,
    holding_months REAL NULL,
    updated_at TEXT NOT NULL,
    moq REAL NOT NULL DEFAULT 0,
    lead_time_days INTEGER NULL,
    order_cycle_months INTEGER NOT NULL DEFAULT 1,
    order_cycle_weeks INTEGER NOT NULL DEFAULT 4,
    holding_days REAL NULL
);
CREATE TABLE IF NOT EXISTS settings_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier TEXT NOT NULL,
    old_value REAL NULL,
    new_value REAL NULL,
    changed_at TEXT NOT NULL,
    field TEXT NOT NULL DEFAULT 'holding_months'
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    file_name TEXT NOT NULL,
    sales_file_name TEXT NOT NULL,
    plan_date TEXT NOT NULL,
    sku_count INTEGER NOT NULL,
    parsed_json TEXT NOT NULL,
    actual_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    pg_file_name TEXT NULL,
    pdg_file_name TEXT NULL,
    stock_json TEXT NULL,
    sit_file_name TEXT NULL
);
"""


# Added to `runs` in v3. A v2 database lacks them; each is added in place, so existing rows are kept.
V3_RUN_COLUMNS = ("pg_file_name", "pdg_file_name", "stock_json")


# Added in v4, when MOQ and lead time moved from the Data sheet to supplier settings.
V4_COLUMNS = (
    ("supplier_settings", "moq", "REAL NOT NULL DEFAULT 0"),
    ("supplier_settings", "lead_time_days", "INTEGER NULL"),
    ("settings_log", "field", "TEXT NOT NULL DEFAULT 'holding_months'"),
)


# Added in v5: how often each principal is ordered from, in months (1 = every month).
V5_COLUMNS = (("supplier_settings", "order_cycle_months", "INTEGER NOT NULL DEFAULT 1"),)


# Added in v6: the order cycle in weeks (default 4). The v5 months column stays but is no longer read.
V6_COLUMNS = (("supplier_settings", "order_cycle_weeks", "INTEGER NOT NULL DEFAULT 4"),)


# Added in v7: the holding in days, filled from the months holding at 30 days a month. The months column stays
# but is no longer read; its change-log lines stay as history.
V7_COLUMNS = (("supplier_settings", "holding_days", "REAL NULL"),)
V7_FILL = "UPDATE supplier_settings SET holding_days = holding_months * 30 WHERE holding_months IS NOT NULL"


# Added in v8: the Stock in Transit file's name for each run (NULL for runs saved before it).
V8_COLUMNS = (("runs", "sit_file_name", "TEXT NULL"),)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    existing = _columns(conn, "runs")
    for column in V3_RUN_COLUMNS:
        if column not in existing:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {column} TEXT NULL")
    _upgrade_to_v4(conn)
    _upgrade_to_v5(conn)
    _add_columns(conn, V6_COLUMNS)
    _add_columns(conn, V7_COLUMNS, fill=V7_FILL)
    _add_columns(conn, V8_COLUMNS)
    if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _upgrade_to_v4(conn: sqlite3.Connection) -> None:
    """Add the v4 columns in place and, when upgrading, pre-fill lead times, all in one transaction
    so an interrupted upgrade leaves the database as it was and runs again on the next start."""
    missing = [(t, c, d) for t, c, d in V4_COLUMNS if c not in _columns(conn, t)]
    if not missing:
        return
    conn.execute("BEGIN")
    try:
        for table, column, definition in missing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        if any(column == "lead_time_days" for _, column, _ in missing):
            _prefill_lead_times(conn)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _upgrade_to_v5(conn: sqlite3.Connection) -> None:
    """Add the order cycle column in place, in one transaction. Every principal starts at 1 (order every
    month), which changes no plan, so nothing is written to the change log."""
    _add_columns(conn, V5_COLUMNS)


def _add_columns(conn: sqlite3.Connection, columns: tuple, fill: str | None = None) -> None:
    """Add the missing columns in place and run `fill` to set their values, in one transaction; nothing is written
    to the change log. v6 gives every principal the 4-week default rather than converting its months cycle;
    v7 converts the holding to days."""
    missing = [(t, c, d) for t, c, d in columns if c not in _columns(conn, t)]
    if not missing:
        return
    conn.execute("BEGIN")
    try:
        for table, column, definition in missing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        if fill:
            conn.execute(fill)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _prefill_lead_times(conn: sqlite3.Connection) -> None:
    """One-time: a supplier whose SKUs in the latest run all had the same Data-sheet lead time gets it."""
    row = conn.execute("SELECT parsed_json FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return
    leads: dict[str, set] = {}
    for sku in json.loads(row[0]).get("skus", []):
        leads.setdefault(sku["supplier"], set()).add(sku.get("lead_time_days"))
    now = datetime.now().isoformat(timespec="seconds")
    stored = {r[0] for r in conn.execute("SELECT supplier FROM supplier_settings")}
    for supplier, values in leads.items():
        lead = next(iter(values)) if len(values) == 1 else None
        if supplier not in stored:
            conn.execute("INSERT INTO supplier_settings (supplier, holding_months, updated_at, moq, lead_time_days)"
                         " VALUES (?, NULL, ?, 0, ?)", (supplier, now, lead))
        elif lead is not None:
            conn.execute("UPDATE supplier_settings SET lead_time_days = ?, updated_at = ? WHERE supplier = ?",
                         (lead, now, supplier))
        if lead is not None:
            conn.execute("INSERT INTO settings_log (supplier, old_value, new_value, changed_at, field)"
                         " VALUES (?, NULL, ?, ?, 'lead_time_days')", (supplier, lead, now))


def _is_v1(db_path: Path) -> bool:
    """A pre-v2 database: old user_version and a supplier_settings table with reorder_days."""
    with closing(sqlite3.connect(db_path)) as conn:
        if conn.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
            return False
        columns = [r[1] for r in conn.execute("PRAGMA table_info(supplier_settings)")]
    return "reorder_days" in columns


def _backup_v1(db_path: Path) -> None:
    target = db_path.with_name(f"{V1_BACKUP_NAME}.db")
    n = 0
    while target.exists():
        n += 1
        target = db_path.with_name(f"{V1_BACKUP_NAME}-{n}.db")
    db_path.rename(target)


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists() and _is_v1(db_path):
        _backup_v1(db_path)  # the connection used for the check is already closed
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    return conn
