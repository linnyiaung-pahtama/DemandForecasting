import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA_VERSION = 2
V1_BACKUP_NAME = "orderplan.v1-backup"

SCHEMA = """
CREATE TABLE IF NOT EXISTS supplier_settings (
    supplier TEXT PRIMARY KEY,
    holding_months REAL NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier TEXT NOT NULL,
    old_value REAL NULL,
    new_value REAL NULL,
    changed_at TEXT NOT NULL
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
    result_json TEXT NOT NULL
);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


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
