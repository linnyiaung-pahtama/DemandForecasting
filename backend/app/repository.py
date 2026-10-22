import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from app.db import connect
from app.models import (
    ParsedInput,
    PlanResult,
    RunListItem,
    RunRecord,
    SupplierSetting,
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Repository:
    """SQLite-backed storage. One connection per call, so it is thread-safe."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        with self._conn():
            pass  # creates the file and schema up front

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        # `with conn` commits/rolls back; closing() releases the handle.
        with closing(connect(self.db_path)) as conn, conn:
            yield conn

    def get_settings(self) -> dict[str, SupplierSetting]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT supplier, reorder_days, target_days, is_default FROM supplier_settings"
            ).fetchall()
        return {
            r["supplier"]: SupplierSetting(
                supplier=r["supplier"],
                reorder_days=r["reorder_days"],
                target_days=r["target_days"],
                is_default=bool(r["is_default"]),
            )
            for r in rows
        }

    def save_settings(self, items: list[SupplierSetting]) -> None:
        now = _now()
        with self._conn() as conn:
            conn.executemany(
                "INSERT INTO supplier_settings"
                " (supplier, reorder_days, target_days, is_default, updated_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(supplier) DO UPDATE SET"
                " reorder_days = excluded.reorder_days,"
                " target_days = excluded.target_days,"
                " is_default = excluded.is_default,"
                " updated_at = excluded.updated_at",
                [(s.supplier, s.reorder_days, s.target_days, int(s.is_default), now) for s in items],
            )

    def add_default_settings(self, items: list[SupplierSetting]) -> None:
        now = _now()
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO supplier_settings"
                " (supplier, reorder_days, target_days, is_default, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                [(s.supplier, s.reorder_days, s.target_days, int(s.is_default), now) for s in items],
            )

    def create_run(self, file_name: str, parsed: ParsedInput, result: PlanResult) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO runs (created_at, file_name, plan_date, parsed_json, result_json)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    _now(),
                    file_name,
                    result.plan_date.isoformat(),
                    parsed.model_dump_json(),
                    result.model_dump_json(),
                ),
            )
            return int(cur.lastrowid)

    def update_run_result(self, run_id: int, result: PlanResult) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE runs SET plan_date = ?, result_json = ? WHERE id = ?",
                (result.plan_date.isoformat(), result.model_dump_json(), run_id),
            )

    def get_run(self, run_id: int) -> RunRecord | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        result = PlanResult.model_validate_json(row["result_json"])
        return RunRecord(
            id=row["id"],
            created_at=row["created_at"],
            file_name=row["file_name"],
            plan_date=row["plan_date"],
            sku_count=len(result.skus),
            parsed=ParsedInput.model_validate_json(row["parsed_json"]),
            result=result,
        )

    def list_runs(self) -> list[RunListItem]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, created_at, file_name, plan_date, result_json FROM runs"
                " ORDER BY id DESC"
            ).fetchall()
        return [
            RunListItem(
                id=r["id"],
                created_at=r["created_at"],
                file_name=r["file_name"],
                plan_date=r["plan_date"],
                sku_count=len(PlanResult.model_validate_json(r["result_json"]).skus),
            )
            for r in rows
        ]

    def latest_run_id(self) -> int | None:
        with self._conn() as conn:
            row = conn.execute("SELECT MAX(id) AS m FROM runs").fetchone()
        return row["m"]
