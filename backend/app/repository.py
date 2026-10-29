import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from app.db import connect
from app.models import (
    ActualSales,
    HoldingPlan,
    ParsedInput,
    RunListItem,
    RunRecord,
    SettingsLogEntry,
    StockResult,
    SupplierSettings,
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

    def get_settings(self) -> dict[str, SupplierSettings]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT supplier, holding_months, moq, lead_time_days, order_cycle_months FROM supplier_settings"
            ).fetchall()
        return {r["supplier"]: _settings(r) for r in rows}

    def save_settings(self, items: list[SupplierSettings]) -> list[SettingsLogEntry]:
        """Upsert settings and log each field whose value changed. A supplier with no stored row
        counts as holding None, MOQ 0, lead time None, order cycle 1."""
        now = _now()
        with self._conn() as conn:
            stored = {r["supplier"]: _settings(r) for r in conn.execute(
                "SELECT supplier, holding_months, moq, lead_time_days, order_cycle_months FROM supplier_settings")}
            log_ids: list[int] = []
            for item in items:
                old = stored.get(item.supplier, SupplierSettings(supplier=item.supplier, holding_months=None,
                                                                 moq=0, lead_time_days=None, order_cycle_months=1))
                changed = [f for f in SETTING_FIELDS if getattr(old, f) != getattr(item, f)]
                if not changed:
                    continue
                conn.execute(
                    "INSERT INTO supplier_settings"
                    " (supplier, holding_months, moq, lead_time_days, order_cycle_months, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(supplier) DO UPDATE SET"
                    " holding_months = excluded.holding_months, moq = excluded.moq,"
                    " lead_time_days = excluded.lead_time_days, order_cycle_months = excluded.order_cycle_months,"
                    " updated_at = excluded.updated_at",
                    (item.supplier, item.holding_months, item.moq, item.lead_time_days, item.order_cycle_months,
                     now),
                )
                for field in changed:
                    cur = conn.execute(
                        "INSERT INTO settings_log (supplier, field, old_value, new_value, changed_at)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (item.supplier, field, getattr(old, field), getattr(item, field), now),
                    )
                    log_ids.append(int(cur.lastrowid))
                stored[item.supplier] = item
            rows = [conn.execute("SELECT * FROM settings_log WHERE id = ?", (i,)).fetchone()
                    for i in log_ids]
        return [_log_entry(r) for r in rows]

    def get_settings_log(self, limit: int = 200) -> list[SettingsLogEntry]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM settings_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_log_entry(r) for r in rows]

    def create_run(self, file_name: str, sales_file_name: str, pg_file_name: str, pdg_file_name: str,
                   parsed: ParsedInput, actual: ActualSales, stock: StockResult, result: HoldingPlan) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO runs (created_at, file_name, sales_file_name, pg_file_name, pdg_file_name,"
                " plan_date, sku_count, parsed_json, actual_json, stock_json, result_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _now(),
                    file_name,
                    sales_file_name,
                    pg_file_name,
                    pdg_file_name,
                    result.plan_date.isoformat(),
                    len(result.skus),
                    parsed.model_dump_json(),
                    actual.model_dump_json(),
                    stock.model_dump_json(),
                    result.model_dump_json(),
                ),
            )
            return int(cur.lastrowid)

    def update_run_result(self, run_id: int, result: HoldingPlan) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE runs SET plan_date = ?, sku_count = ?, result_json = ? WHERE id = ?",
                (result.plan_date.isoformat(), len(result.skus), result.model_dump_json(), run_id),
            )

    def get_run(self, run_id: int) -> RunRecord | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return RunRecord(
            id=row["id"],
            created_at=row["created_at"],
            file_name=row["file_name"],
            sales_file_name=row["sales_file_name"],
            pg_file_name=row["pg_file_name"],
            pdg_file_name=row["pdg_file_name"],
            plan_date=row["plan_date"],
            sku_count=row["sku_count"],
            parsed=ParsedInput.model_validate_json(row["parsed_json"]),
            actual=ActualSales.model_validate_json(row["actual_json"]),
            stock=StockResult.model_validate_json(row["stock_json"]) if row["stock_json"] else None,
            result=HoldingPlan.model_validate_json(row["result_json"]),
        )

    def list_runs(self) -> list[RunListItem]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, created_at, file_name, sales_file_name, pg_file_name, pdg_file_name,"
                " plan_date, sku_count"
                " FROM runs ORDER BY id DESC"
            ).fetchall()
        return [RunListItem(**dict(r)) for r in rows]

    def latest_run_id(self) -> int | None:
        with self._conn() as conn:
            row = conn.execute("SELECT MAX(id) AS m FROM runs").fetchone()
        return row["m"]


SETTING_FIELDS = ("holding_months", "moq", "lead_time_days", "order_cycle_months")


def _settings(row: sqlite3.Row) -> SupplierSettings:
    return SupplierSettings(supplier=row["supplier"], holding_months=row["holding_months"],
                            moq=row["moq"], lead_time_days=row["lead_time_days"],
                            order_cycle_months=row["order_cycle_months"])


def _log_entry(row: sqlite3.Row) -> SettingsLogEntry:
    return SettingsLogEntry(
        id=row["id"],
        supplier=row["supplier"],
        field=row["field"],
        old_value=row["old_value"],
        new_value=row["new_value"],
        changed_at=row["changed_at"],
    )
