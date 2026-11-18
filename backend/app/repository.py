from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

import psycopg

from app.db import connect, init_schema
from app.models import (
    DEFAULT_ORDER_CYCLE_WEEKS,
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
    """PostgreSQL storage. One connection per call (committed on success, rolled back on an error), so it is
    thread-safe."""

    def __init__(self, database_url: str | None = None, schema: str | None = None):
        self.database_url = database_url
        self.schema = schema
        with self._conn() as conn:
            init_schema(conn)  # creates the tables up front

    @contextmanager
    def _conn(self) -> Iterator[psycopg.Connection]:
        with connect(self.database_url, self.schema) as conn:
            yield conn

    def get_settings(self) -> dict[str, SupplierSettings]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT supplier, holding_days, moq, lead_time_days, order_cycle_weeks FROM supplier_settings"
            ).fetchall()
        return {r["supplier"]: _settings(r) for r in rows}

    def save_settings(self, items: list[SupplierSettings]) -> list[SettingsLogEntry]:
        """Upsert settings and log each field whose value changed. A supplier with no stored row
        counts as holding None, MOQ 0, lead time None, order cycle 4 weeks."""
        now = _now()
        with self._conn() as conn:
            stored = {r["supplier"]: _settings(r) for r in conn.execute(
                "SELECT supplier, holding_days, moq, lead_time_days, order_cycle_weeks FROM supplier_settings")}
            log_ids: list[int] = []
            for item in items:
                old = stored.get(item.supplier, SupplierSettings(supplier=item.supplier, holding_days=None,
                                                                 moq=0, lead_time_days=None,
                                                                 order_cycle_weeks=DEFAULT_ORDER_CYCLE_WEEKS))
                changed = [f for f in SETTING_FIELDS if getattr(old, f) != getattr(item, f)]
                if not changed:
                    continue
                conn.execute(
                    "INSERT INTO supplier_settings"
                    " (supplier, holding_days, moq, lead_time_days, order_cycle_weeks, updated_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s)"
                    " ON CONFLICT (supplier) DO UPDATE SET"
                    " holding_days = excluded.holding_days, moq = excluded.moq,"
                    " lead_time_days = excluded.lead_time_days, order_cycle_weeks = excluded.order_cycle_weeks,"
                    " updated_at = excluded.updated_at",
                    (item.supplier, item.holding_days, item.moq, item.lead_time_days, item.order_cycle_weeks,
                     now),
                )
                for field in changed:
                    row = conn.execute(
                        "INSERT INTO settings_log (supplier, field, old_value, new_value, changed_at)"
                        " VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (item.supplier, field, getattr(old, field), getattr(item, field), now),
                    ).fetchone()
                    log_ids.append(int(row["id"]))
                stored[item.supplier] = item
            rows = [conn.execute("SELECT * FROM settings_log WHERE id = %s", (i,)).fetchone()
                    for i in log_ids]
        return [_log_entry(r) for r in rows]

    def get_settings_log(self, limit: int = 200) -> list[SettingsLogEntry]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM settings_log ORDER BY id DESC LIMIT %s", (limit,)
            ).fetchall()
        return [_log_entry(r) for r in rows]

    def create_run(self, file_name: str, sales_file_name: str, pg_file_name: str, pdg_file_name: str,
                   sit_file_name: str, parsed: ParsedInput, actual: ActualSales, stock: StockResult,
                   result: HoldingPlan) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "INSERT INTO runs (created_at, file_name, sales_file_name, pg_file_name, pdg_file_name,"
                " sit_file_name, plan_date, sku_count, parsed_json, actual_json, stock_json, result_json)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    _now(),
                    file_name,
                    sales_file_name,
                    pg_file_name,
                    pdg_file_name,
                    sit_file_name,
                    result.plan_date.isoformat(),
                    len({s.sap_code for s in result.skus}),
                    parsed.model_dump_json(),
                    actual.model_dump_json(),
                    stock.model_dump_json(),
                    result.model_dump_json(),
                ),
            ).fetchone()
            return int(row["id"])

    def update_run_result(self, run_id: int, result: HoldingPlan) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE runs SET plan_date = %s, sku_count = %s, result_json = %s WHERE id = %s",
                (result.plan_date.isoformat(), len({s.sap_code for s in result.skus}), result.model_dump_json(), run_id),
            )

    def update_run_inputs(self, run_id: int, parsed: ParsedInput, result: HoldingPlan) -> None:
        """Save a run's changed inputs (its commits) and its recalculated result in place."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE runs SET parsed_json = %s, plan_date = %s, sku_count = %s, result_json = %s WHERE id = %s",
                (parsed.model_dump_json(), result.plan_date.isoformat(), len({s.sap_code for s in result.skus}),
                 result.model_dump_json(), run_id),
            )

    def get_run(self, run_id: int) -> RunRecord | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = %s", (run_id,)).fetchone()
        if row is None:
            return None
        return RunRecord(
            id=row["id"],
            created_at=row["created_at"],
            file_name=row["file_name"],
            sales_file_name=row["sales_file_name"],
            pg_file_name=row["pg_file_name"],
            pdg_file_name=row["pdg_file_name"],
            sit_file_name=row["sit_file_name"],
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
                "SELECT id, created_at, file_name, sales_file_name, pg_file_name, pdg_file_name, sit_file_name,"
                " plan_date, sku_count"
                " FROM runs ORDER BY id DESC"
            ).fetchall()
        return [RunListItem(**r) for r in rows]

    def latest_run_id(self) -> int | None:
        with self._conn() as conn:
            row = conn.execute("SELECT MAX(id) AS m FROM runs").fetchone()
        return row["m"]


SETTING_FIELDS = ("holding_days", "moq", "lead_time_days", "order_cycle_weeks")


def _settings(row: dict) -> SupplierSettings:
    return SupplierSettings(supplier=row["supplier"], holding_days=row["holding_days"],
                            moq=row["moq"], lead_time_days=row["lead_time_days"],
                            order_cycle_weeks=row["order_cycle_weeks"])


def _log_entry(row: dict) -> SettingsLogEntry:
    return SettingsLogEntry(
        id=row["id"],
        supplier=row["supplier"],
        field=row["field"],
        old_value=row["old_value"],
        new_value=row["new_value"],
        changed_at=row["changed_at"],
    )
