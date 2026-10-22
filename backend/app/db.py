import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS supplier_settings (
    supplier TEXT PRIMARY KEY,
    reorder_days INTEGER NOT NULL,
    target_days INTEGER NOT NULL,
    is_default INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    file_name TEXT NOT NULL,
    plan_date TEXT NOT NULL,
    parsed_json TEXT NOT NULL,
    result_json TEXT NOT NULL
);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    return conn
