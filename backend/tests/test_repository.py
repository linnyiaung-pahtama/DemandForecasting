import sqlite3

from app.holding import plan_sku
from app.models import HoldingPlan, SupplierHolding
from app.parsing import parse_input
from app.repository import Repository
from app.sales import actual_cartons, parse_sales
from tests.helpers import make_sales_workbook, make_workbook

SALES_ROW = lambda code, month, qty: ["PG", "Yangon", "P", "B", code, "x", 2026, month, qty, 0]


def _build_run():
    parsed = parse_input(make_workbook([["1", "A", "x", 12, 0, 6, 7, 5, 0, 0, 0] + [300] * 12]))
    actual = actual_cartons(
        parse_sales(make_sales_workbook([SALES_ROW("1", m, 120) for m in ("Jul", "Aug", "Sep")])), parsed)
    sku = plan_sku(parsed.skus[0], actual.cartons.get("1", {}), actual.months,
                   parsed.forecast_months[:3], 3, parsed.default_plan_date)
    result = HoldingPlan(
        plan_date=parsed.default_plan_date, actual_months=actual.months,
        forecast_months=parsed.forecast_months[:3], skus=[sku],
        settings_used=[SupplierHolding(supplier="A", holding_months=3)], blocked_suppliers=[],
        counts={"TO_ORDER": 1, "NO_ORDER_NEEDED": 0, "HOLDING_NOT_SET": 0,
                "NO_DEMAND_DATA": 0, "ZERO_FORECAST": 0})
    return parsed, actual, result


def test_holdings_and_log(tmp_path):
    repo = Repository(tmp_path / "t.db")
    repo.save_holdings([SupplierHolding(supplier="A", holding_months=3)])
    repo.save_holdings([SupplierHolding(supplier="A", holding_months=3)])      # unchanged: no log
    repo.save_holdings([SupplierHolding(supplier="A", holding_months=2.5)])
    repo.save_holdings([SupplierHolding(supplier="A", holding_months=None)])   # cleared
    assert repo.get_holdings() == {}
    log = repo.get_settings_log()
    assert [(e.old_value, e.new_value) for e in log] == [(2.5, None), (3, 2.5), (None, 3)]


def test_save_holdings_returns_only_new_entries_and_limit(tmp_path):
    repo = Repository(tmp_path / "t.db")
    first = repo.save_holdings([SupplierHolding(supplier="A", holding_months=3),
                                SupplierHolding(supplier="B", holding_months=None)])
    assert [(e.supplier, e.old_value, e.new_value) for e in first] == [("A", None, 3)]
    second = repo.save_holdings([SupplierHolding(supplier="A", holding_months=3),
                                 SupplierHolding(supplier="B", holding_months=1.5)])
    assert [(e.supplier, e.old_value, e.new_value) for e in second] == [("B", None, 1.5)]
    assert repo.get_holdings() == {"A": 3, "B": 1.5}
    assert len(repo.get_settings_log(limit=1)) == 1
    assert repo.get_settings_log(limit=1)[0].supplier == "B"


def test_v1_database_is_backed_up_and_replaced(tmp_path):
    db = tmp_path / "orderplan.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE supplier_settings (supplier TEXT PRIMARY KEY, reorder_days INTEGER NOT NULL, "
                  "target_days INTEGER NOT NULL, is_default INTEGER NOT NULL, updated_at TEXT NOT NULL)")
        c.execute("INSERT INTO supplier_settings VALUES ('A', 20, 30, 1, 'x')")
    c.close()
    repo = Repository(db)
    assert (tmp_path / "orderplan.v1-backup.db").exists()
    assert repo.get_holdings() == {} and repo.list_runs() == []


def test_v1_backup_name_does_not_overwrite_existing_backup(tmp_path):
    (tmp_path / "orderplan.v1-backup.db").write_bytes(b"older")
    db = tmp_path / "other.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE supplier_settings (supplier TEXT PRIMARY KEY, reorder_days INTEGER NOT NULL, "
                  "target_days INTEGER NOT NULL, is_default INTEGER NOT NULL, updated_at TEXT NOT NULL)")
    c.close()
    Repository(db)
    assert (tmp_path / "orderplan.v1-backup.db").read_bytes() == b"older"
    assert (tmp_path / "orderplan.v1-backup-1.db").exists()


def test_v2_database_is_kept_on_reopen(tmp_path):
    db = tmp_path / "orderplan.db"
    Repository(db).save_holdings([SupplierHolding(supplier="A", holding_months=3)])
    assert Repository(db).get_holdings() == {"A": 3}
    assert not (tmp_path / "orderplan.v1-backup.db").exists()


def test_run_round_trip(tmp_path):
    repo = Repository(tmp_path / "t.db")
    parsed, actual, result = _build_run()
    run_id = repo.create_run("in.xlsx", "sales.xlsx", parsed, actual, result)
    rec = repo.get_run(run_id)
    assert rec.file_name == "in.xlsx" and rec.sales_file_name == "sales.xlsx"
    assert rec.result == result and rec.parsed == parsed and rec.actual == actual
    assert rec.sku_count == 1 and rec.plan_date == result.plan_date
    assert [r.id for r in repo.list_runs()] == [run_id] and repo.latest_run_id() == run_id
    assert repo.list_runs()[0].sku_count == 1 and repo.list_runs()[0].sales_file_name == "sales.xlsx"
    assert repo.get_run(999) is None


def test_update_run_result_and_list_newest_first(tmp_path):
    repo = Repository(tmp_path / "sub" / "t.db")
    parsed, actual, result = _build_run()
    first = repo.create_run("a.xlsx", "s.xlsx", parsed, actual, result)
    second = repo.create_run("b.xlsx", "s.xlsx", parsed, actual, result)
    assert [r.id for r in repo.list_runs()] == [second, first]
    changed = result.model_copy(update={"counts": {**result.counts, "TO_ORDER": 0}})
    repo.update_run_result(first, changed)
    assert repo.get_run(first).result == changed
    assert repo.get_run(second).result == result
    assert repo.latest_run_id() == second


def test_latest_run_id_empty(tmp_path):
    assert Repository(tmp_path / "t.db").latest_run_id() is None
