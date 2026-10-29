import json
import sqlite3
from contextlib import closing

from fastapi.testclient import TestClient

from app.holding import plan_sku
from app.main import create_app
from app.models import HoldingPlan, StockFileSummary, StockResult, SupplierSettings
from app.parsing import parse_input
from app.repository import Repository
from app.sales import actual_cartons, parse_sales
from tests.helpers import make_sales_workbook, make_workbook

SALES_ROW = lambda code, month, qty: ["PG", "Yangon", "P", "B", code, "x", 2026, month, qty, 0]


def _stock():
    def summary(source):
        return StockFileSummary(source=source, as_of=None, skus_with_stock=1, sellable_cartons=5, non_sellable_cartons=0)
    return StockResult(pg=summary("PG"), pdg=summary("PDG"), skus_with_stock=1, warnings=[])


V2_SCHEMA = """
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
BREAKDOWN_KEYS = ("pg_sellable", "pdg_sellable", "pg_non_sellable", "pdg_non_sellable")


def _without_breakdown(model) -> str:
    """The model's JSON as a v2 build stored it: no stock-breakdown keys on any SKU."""
    data = json.loads(model.model_dump_json())
    for sku in data["skus"]:
        for key in BREAKDOWN_KEYS:
            del sku[key]
    return json.dumps(data)


def _build_run():
    parsed = parse_input(make_workbook([["1", "A", "x", 12, 0, 6, 7, 5, 0, 0, 0] + [300] * 12]))
    actual = actual_cartons(
        parse_sales(make_sales_workbook([SALES_ROW("1", m, 120) for m in ("Jul", "Aug", "Sep")])), parsed)
    sku = plan_sku(parsed.skus[0], actual.cartons.get("1", {}), actual.months,
                   parsed.forecast_months[:3], 3, parsed.default_plan_date)
    result = HoldingPlan(
        plan_date=parsed.default_plan_date, actual_months=actual.months,
        forecast_months=parsed.forecast_months[:3], skus=[sku],
        settings_used=[SupplierSettings(supplier="A", holding_months=3, moq=0, lead_time_days=7)], blocked_suppliers=[],
        counts={"TO_ORDER": 1, "NO_ORDER_NEEDED": 0, "HOLDING_NOT_SET": 0,
                "NO_DEMAND_DATA": 0, "ZERO_FORECAST": 0})
    return parsed, actual, result


def S(supplier, holding, moq=0, lead=None):
    return SupplierSettings(supplier=supplier, holding_months=holding, moq=moq, lead_time_days=lead)


def test_holdings_and_log(tmp_path):
    repo = Repository(tmp_path / "t.db")
    repo.save_settings([S("A", 3)])
    repo.save_settings([S("A", 3)])      # unchanged: no log
    repo.save_settings([S("A", 2.5)])
    repo.save_settings([S("A", None)])   # cleared
    assert repo.get_settings() == {"A": S("A", None)}
    log = repo.get_settings_log()
    assert [(e.field, e.old_value, e.new_value) for e in log] == [
        ("holding_months", 2.5, None), ("holding_months", 3, 2.5), ("holding_months", None, 3)]


def test_save_settings_returns_only_new_entries_and_limit(tmp_path):
    repo = Repository(tmp_path / "t.db")
    first = repo.save_settings([S("A", 3), S("B", None)])
    assert [(e.supplier, e.old_value, e.new_value) for e in first] == [("A", None, 3)]
    second = repo.save_settings([S("A", 3), S("B", 1.5)])
    assert [(e.supplier, e.old_value, e.new_value) for e in second] == [("B", None, 1.5)]
    assert repo.get_settings() == {"A": S("A", 3), "B": S("B", 1.5)}
    assert len(repo.get_settings_log(limit=1)) == 1
    assert repo.get_settings_log(limit=1)[0].supplier == "B"


def test_save_settings_logs_each_changed_field(tmp_path):
    repo = Repository(tmp_path / "t.db")
    repo.save_settings([S("A", 2, 0, 14)])
    second = repo.save_settings([S("A", 2, 8000, None)])
    assert sorted((e.field, e.old_value, e.new_value) for e in second) == [
        ("lead_time_days", 14, None), ("moq", 0, 8000)]
    assert repo.get_settings()["A"] == S("A", 2, 8000, None)
    assert repo.save_settings([S("A", 2, 8000, None)]) == []


def test_fresh_database_has_no_prefill(tmp_path):
    repo = Repository(tmp_path / "t.db")
    assert repo.get_settings() == {} and repo.get_settings_log() == []


def test_v1_database_is_backed_up_and_replaced(tmp_path):
    db = tmp_path / "orderplan.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE supplier_settings (supplier TEXT PRIMARY KEY, reorder_days INTEGER NOT NULL, "
                  "target_days INTEGER NOT NULL, is_default INTEGER NOT NULL, updated_at TEXT NOT NULL)")
        c.execute("INSERT INTO supplier_settings VALUES ('A', 20, 30, 1, 'x')")
    c.close()
    repo = Repository(db)
    assert (tmp_path / "orderplan.v1-backup.db").exists()
    assert repo.get_settings() == {} and repo.list_runs() == []


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
    Repository(db).save_settings([S("A", 3)])
    assert Repository(db).get_settings() == {"A": S("A", 3)}
    assert not (tmp_path / "orderplan.v1-backup.db").exists()


def test_run_round_trip(tmp_path):
    repo = Repository(tmp_path / "t.db")
    parsed, actual, result = _build_run()
    stock = _stock()
    run_id = repo.create_run("in.xlsx", "sales.xlsx", "pg.xlsx", "pdg.xlsx", parsed, actual, stock, result)
    rec = repo.get_run(run_id)
    assert rec.file_name == "in.xlsx" and rec.sales_file_name == "sales.xlsx"
    assert rec.pg_file_name == "pg.xlsx" and rec.pdg_file_name == "pdg.xlsx" and rec.stock == stock
    assert rec.result == result and rec.parsed == parsed and rec.actual == actual
    assert rec.sku_count == 1 and rec.plan_date == result.plan_date
    assert [r.id for r in repo.list_runs()] == [run_id] and repo.latest_run_id() == run_id
    assert repo.list_runs()[0].sku_count == 1 and repo.list_runs()[0].sales_file_name == "sales.xlsx"
    assert repo.list_runs()[0].pg_file_name == "pg.xlsx" and repo.list_runs()[0].pdg_file_name == "pdg.xlsx"
    assert repo.get_run(999) is None


def test_update_run_result_and_list_newest_first(tmp_path):
    repo = Repository(tmp_path / "sub" / "t.db")
    parsed, actual, result = _build_run()
    first = repo.create_run("a.xlsx", "s.xlsx", "p.xlsx", "d.xlsx", parsed, actual, _stock(), result)
    second = repo.create_run("b.xlsx", "s.xlsx", "p.xlsx", "d.xlsx", parsed, actual, _stock(), result)
    assert [r.id for r in repo.list_runs()] == [second, first]
    changed = result.model_copy(update={"counts": {**result.counts, "TO_ORDER": 0}})
    repo.update_run_result(first, changed)
    assert repo.get_run(first).result == changed
    assert repo.get_run(second).result == result
    assert repo.latest_run_id() == second


def test_latest_run_id_empty(tmp_path):
    assert Repository(tmp_path / "t.db").latest_run_id() is None


def test_v2_database_is_migrated_in_place(tmp_path):
    parsed, actual, result = _build_run()
    # a v2 run kept its stock in the Data sheet, so its SKU carries real sellable and SIT figures
    parsed = parsed.model_copy(update={"skus": [parsed.skus[0].model_copy(update={"sellable": 7.0, "sit": 3.0})]})
    result = result.model_copy(update={"skus": [plan_sku(
        parsed.skus[0], actual.cartons.get("1", {}), actual.months, parsed.forecast_months[:3], 3,
        parsed.default_plan_date)]})
    assert result.skus[0].sellable == 7 and result.skus[0].sit == 3
    db = tmp_path / "v2.db"
    with closing(sqlite3.connect(db)) as c:
        c.executescript(V2_SCHEMA)
        c.execute("INSERT INTO supplier_settings VALUES ('CFC', 2.0, '2026-10-01T00:00:00')")
        c.execute("INSERT INTO runs (created_at, file_name, sales_file_name, plan_date, sku_count,"
                  " parsed_json, actual_json, result_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  ("2026-10-12T09:00:00", "in.xlsx", "sales.xlsx", result.plan_date.isoformat(), 1,
                   _without_breakdown(parsed), actual.model_dump_json(), _without_breakdown(result)))
        c.execute("PRAGMA user_version = 2")
        c.commit()
    repo = Repository(db)
    assert db.exists() and not list(tmp_path.glob("orderplan.v1-backup*.db"))
    assert list(tmp_path.glob("*.db")) == [db]
    run = repo.get_run(1)
    assert run.stock is None and run.parsed.skus[0].pg_sellable is None and run.result.skus[0].pg_sellable is None
    assert run.file_name == "in.xlsx" and run.actual == actual
    assert repo.list_runs()[0].pg_file_name is None and repo.list_runs()[0].pdg_file_name is None
    settings = repo.get_settings()
    assert settings["CFC"] == S("CFC", 2.0)
    # the v4 step pre-fills from the latest run, whose supplier "A" had lead time 7 in its Data sheet
    assert set(settings) == {"CFC", "A"} and settings["A"].holding_months is None
    with closing(sqlite3.connect(db)) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 4
        columns = [r[1] for r in c.execute("PRAGMA table_info(runs)")]
        assert columns[-3:] == ["pg_file_name", "pdg_file_name", "stock_json"]
        before = c.execute("SELECT * FROM runs").fetchall()
    Repository(db)  # a second open changes nothing
    with closing(sqlite3.connect(db)) as c:
        assert c.execute("SELECT * FROM runs").fetchall() == before
        assert [r[1] for r in c.execute("PRAGMA table_info(runs)")] == columns
    rec = TestClient(create_app(db)).post("/api/runs/1/recalculate")
    assert rec.status_code == 200 and rec.json()["stock"] is None
    sku = rec.json()["result"]["skus"][0]
    assert (sku["sellable"], sku["sit"], sku["available"]) == (7, 3, 10) and sku["pg_sellable"] is None


V3_SCHEMA = V2_SCHEMA.replace(
    "    result_json TEXT NOT NULL\n);",
    "    result_json TEXT NOT NULL,\n    pg_file_name TEXT NULL,\n    pdg_file_name TEXT NULL,\n    stock_json TEXT NULL\n);")


def test_v3_database_is_upgraded_to_v4_with_lead_times_prefilled(tmp_path):
    parsed, actual, result = _build_run()
    base = parsed.skus[0]
    skus = [base.model_copy(update={"sap_code": code, "supplier": sup, "lead_time_days": lead})
            for code, sup, lead in (("1", "A", 14), ("2", "A", 14), ("3", "B", 7), ("4", "B", None),
                                    ("5", "C", 21))]
    latest = parsed.model_copy(update={"skus": skus})
    older = parsed.model_copy(update={"skus": [base.model_copy(update={"supplier": "D", "lead_time_days": 3})]})
    db = tmp_path / "v3.db"
    with closing(sqlite3.connect(db)) as c:
        c.executescript(V3_SCHEMA)
        c.execute("INSERT INTO supplier_settings VALUES ('A', 2.0, '2026-10-01T00:00:00')")
        c.execute("INSERT INTO supplier_settings VALUES ('D', 3.0, '2026-10-01T00:00:00')")
        c.execute("INSERT INTO settings_log (supplier, old_value, new_value, changed_at)"
                  " VALUES ('A', NULL, 2.0, '2026-10-01T00:00:00')")
        for p in (older, latest):
            c.execute("INSERT INTO runs (created_at, file_name, sales_file_name, plan_date, sku_count,"
                      " parsed_json, actual_json, result_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      ("2026-10-12T09:00:00", "in.xlsx", "sales.xlsx", result.plan_date.isoformat(),
                       len(p.skus), p.model_dump_json(), actual.model_dump_json(), result.model_dump_json()))
        c.execute("PRAGMA user_version = 3")
        c.commit()
        runs_before = c.execute("SELECT * FROM runs").fetchall()

    repo = Repository(db)
    s = repo.get_settings()
    assert (s["A"].holding_months, s["A"].moq, s["A"].lead_time_days) == (2.0, 0, 14)
    assert s["B"].lead_time_days is None and s["B"].holding_months is None and s["B"].moq == 0
    assert s["D"].lead_time_days is None and s["D"].moq == 0 and s["D"].holding_months == 3.0
    assert (s["C"].holding_months, s["C"].moq, s["C"].lead_time_days) == (None, 0, 21)
    log = repo.get_settings_log()
    assert sorted((e.supplier, e.field, e.old_value, e.new_value) for e in log[:2]) == [
        ("A", "lead_time_days", None, 14), ("C", "lead_time_days", None, 21)]
    assert len(log) == 3 and log[-1].field == "holding_months"
    with closing(sqlite3.connect(db)) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 4
        assert c.execute("SELECT * FROM runs").fetchall() == runs_before
        settings_before = c.execute("SELECT * FROM supplier_settings ORDER BY supplier").fetchall()

    Repository(db)  # a second open changes nothing
    assert len(repo.get_settings_log()) == 3
    with closing(sqlite3.connect(db)) as c:
        assert c.execute("SELECT * FROM supplier_settings ORDER BY supplier").fetchall() == settings_before
