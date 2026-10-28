from pathlib import Path

from app import config


def test_tests_never_use_the_real_database():
    import app.main  # noqa: F401  (importing the app module must not touch the planner's database)
    real = Path(config.__file__).resolve().parent.parent / "data" / "orderplan.db"
    assert Path(config.DB_PATH).resolve() != real
    assert not hasattr(app.main, "app")  # no module-level app: the server uses the factory


def test_user_version_is_written_only_when_it_differs():
    import sqlite3
    from app.db import SCHEMA_VERSION, init_schema
    conn = sqlite3.connect(":memory:")
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    init_schema(conn)
    assert any("user_version =" in s for s in statements)   # fresh database: stamped
    statements.clear()
    init_schema(conn)
    assert not any("user_version =" in s for s in statements)  # already current: no write
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
