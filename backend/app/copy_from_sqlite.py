"""Copy the tool's old SQLite file (orderplan.db, version 8) into an empty PostgreSQL database.

    python -m app.copy_from_sqlite data/orderplan.db

Writes to DATABASE_URL (backend/.env). Refuses unless the file is at version 8 (open it once with the last
SQLite version of the tool, which upgrades it) and the PostgreSQL tables are empty, so nothing is overwritten.
Copies the three tables in one transaction keeping their IDs, moves the ID counters past the highest copied ID
(so new rows don't collide), and checks the row counts on both sides. The SQLite file is not changed.
"""
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from app.db import SCHEMA_VERSION, connect, init_schema

TABLES = {"supplier_settings": None, "settings_log": "id", "runs": "id"}  # table -> its ID column, if any


def copy(sqlite_path: str | Path, database_url: str | None = None,
         schema: str | None = None) -> dict[str, tuple[int, int]]:
    """Copy and return {table: (rows in SQLite, rows in PostgreSQL)}. Raises SystemExit with a message when it
    refuses or the counts differ; then nothing is written."""
    path = Path(sqlite_path)
    if not path.is_file():
        raise SystemExit(f"No such file: {path}")
    with closing(sqlite3.connect(path)) as src:
        src.row_factory = sqlite3.Row
        version = src.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            raise SystemExit(f"{path} is at version {version}, not {SCHEMA_VERSION}: open it once with the last "
                             "SQLite version of the tool (it upgrades the file), then copy it.")
        with connect(database_url, schema) as dst:  # one transaction: rolled back on any error
            init_schema(dst)
            busy = {t: n for t in TABLES if (n := dst.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"])}
            if busy:
                raise SystemExit("PostgreSQL already has data, nothing copied: "
                                 + ", ".join(f"{t} ({n} rows)" for t, n in busy.items()))
            counts = {}
            for table, id_column in TABLES.items():
                rows = src.execute(f"SELECT * FROM {table}").fetchall()
                if rows:
                    columns = rows[0].keys()
                    with dst.cursor() as cur:
                        cur.executemany(f"INSERT INTO {table} ({', '.join(columns)})"
                                        f" VALUES ({', '.join(['%s'] * len(columns))})", [tuple(r) for r in rows])
                if id_column:
                    dst.execute(f"SELECT setval(pg_get_serial_sequence('{table}', '{id_column}'),"
                                f" COALESCE((SELECT MAX({id_column}) FROM {table}), 0) + 1, false)")
                counts[table] = (len(rows), dst.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"])
            if any(a != b for a, b in counts.values()):
                raise SystemExit(f"Row counts differ (SQLite, PostgreSQL), nothing copied: {counts}")
    return counts


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    counts = copy(sys.argv[1])
    print(f"{'table':<20} {'SQLite':>8} {'PostgreSQL':>11}")
    for table, (a, b) in counts.items():
        print(f"{table:<20} {a:>8} {b:>11}")
    print("Done: every table copied and counts match.")


if __name__ == "__main__":
    main()
