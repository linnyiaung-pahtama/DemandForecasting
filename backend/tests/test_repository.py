from app.holding import plan_sku
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


def _build_run():
    parsed = parse_input(make_workbook([["1", "A", "x", 12, 0, 6, 7, 5, 0, 0, 0] + [300] * 12]))
    actual = actual_cartons(
        parse_sales(make_sales_workbook([SALES_ROW("1", m, 120) for m in ("Jul", "Aug", "Sep")])), parsed)
    sku = plan_sku(parsed.skus[0], actual.cartons.get("1", {}), actual.months,
                   parsed.forecast_months[:3], 90, parsed.default_plan_date)
    result = HoldingPlan(
        plan_date=parsed.default_plan_date, actual_months=actual.months,
        forecast_months=parsed.forecast_months[:3], skus=[sku],
        settings_used=[SupplierSettings(supplier="A", holding_days=90, moq=0, lead_time_days=7)], blocked_suppliers=[],
        counts={"TO_ORDER": 1, "NO_ORDER_NEEDED": 0, "HOLDING_NOT_SET": 0,
                "NO_DEMAND_DATA": 0, "ZERO_FORECAST": 0})
    return parsed, actual, result


def S(supplier, holding, moq=0, lead=None, cycle=4):
    return SupplierSettings(supplier=supplier, holding_days=holding, moq=moq, lead_time_days=lead,
                            order_cycle_weeks=cycle)


def test_order_cycle_saved_and_logged(db):
    repo = Repository(**db)
    repo.save_settings([S("A", 2, cycle=3)])
    assert repo.get_settings()["A"].order_cycle_weeks == 3
    log = repo.get_settings_log()
    assert {(e.field, e.old_value, e.new_value) for e in log} == {("holding_days", None, 2),
                                                                  ("order_cycle_weeks", 4, 3)}
    assert repo.save_settings([S("A", 2, cycle=3)]) == []
    second = repo.save_settings([S("A", 2, cycle=4)])
    assert [(e.field, e.old_value, e.new_value) for e in second] == [("order_cycle_weeks", 3, 4)]


def test_holdings_and_log(db):
    repo = Repository(**db)
    repo.save_settings([S("A", 3)])
    repo.save_settings([S("A", 3)])      # unchanged: no log
    repo.save_settings([S("A", 2.5)])
    repo.save_settings([S("A", None)])   # cleared
    assert repo.get_settings() == {"A": S("A", None)}
    log = repo.get_settings_log()
    assert [(e.field, e.old_value, e.new_value) for e in log] == [
        ("holding_days", 2.5, None), ("holding_days", 3, 2.5), ("holding_days", None, 3)]


def test_save_settings_returns_only_new_entries_and_limit(db):
    repo = Repository(**db)
    first = repo.save_settings([S("A", 3), S("B", None)])
    assert [(e.supplier, e.old_value, e.new_value) for e in first] == [("A", None, 3)]
    second = repo.save_settings([S("A", 3), S("B", 1.5)])
    assert [(e.supplier, e.old_value, e.new_value) for e in second] == [("B", None, 1.5)]
    assert repo.get_settings() == {"A": S("A", 3), "B": S("B", 1.5)}
    assert len(repo.get_settings_log(limit=1)) == 1
    assert repo.get_settings_log(limit=1)[0].supplier == "B"


def test_save_settings_logs_each_changed_field(db):
    repo = Repository(**db)
    repo.save_settings([S("A", 2, 0, 14)])
    second = repo.save_settings([S("A", 2, 8000, None)])
    assert sorted((e.field, e.old_value, e.new_value) for e in second) == [
        ("lead_time_days", 14, None), ("moq", 0, 8000)]
    assert repo.get_settings()["A"] == S("A", 2, 8000, None)
    assert repo.save_settings([S("A", 2, 8000, None)]) == []


def test_fresh_database_has_no_prefill(db):
    repo = Repository(**db)
    assert repo.get_settings() == {} and repo.get_settings_log() == []


def test_data_is_kept_on_reopen(db):
    Repository(**db).save_settings([S("A", 3)])
    assert Repository(**db).get_settings() == {"A": S("A", 3)}   # opening again creates nothing and loses nothing
    assert len(Repository(**db).get_settings_log()) == 1


def test_run_round_trip(db):
    repo = Repository(**db)
    parsed, actual, result = _build_run()
    stock = _stock()
    run_id = repo.create_run("in.xlsx", "sales.xlsx", "pg.xlsx", "pdg.xlsx", "sit.xlsx", parsed, actual, stock, result)
    rec = repo.get_run(run_id)
    assert rec.file_name == "in.xlsx" and rec.sales_file_name == "sales.xlsx"
    assert rec.pg_file_name == "pg.xlsx" and rec.pdg_file_name == "pdg.xlsx" and rec.stock == stock
    assert rec.result == result and rec.parsed == parsed and rec.actual == actual
    assert rec.sku_count == 1 and rec.plan_date == result.plan_date
    assert [r.id for r in repo.list_runs()] == [run_id] and repo.latest_run_id() == run_id
    assert repo.list_runs()[0].sku_count == 1 and repo.list_runs()[0].sales_file_name == "sales.xlsx"
    assert repo.list_runs()[0].pg_file_name == "pg.xlsx" and repo.list_runs()[0].pdg_file_name == "pdg.xlsx"
    assert rec.sit_file_name == "sit.xlsx" and repo.list_runs()[0].sit_file_name == "sit.xlsx"
    assert repo.get_run(999) is None


def test_update_run_result_and_list_newest_first(db):
    repo = Repository(**db)
    parsed, actual, result = _build_run()
    first = repo.create_run("a.xlsx", "s.xlsx", "p.xlsx", "d.xlsx", "t.xlsx", parsed, actual, _stock(), result)
    second = repo.create_run("b.xlsx", "s.xlsx", "p.xlsx", "d.xlsx", "t.xlsx", parsed, actual, _stock(), result)
    assert [r.id for r in repo.list_runs()] == [second, first]
    changed = result.model_copy(update={"counts": {**result.counts, "TO_ORDER": 0}})
    repo.update_run_result(first, changed)
    assert repo.get_run(first).result == changed
    assert repo.get_run(second).result == result
    assert repo.latest_run_id() == second


def test_latest_run_id_empty(db):
    assert Repository(**db).latest_run_id() is None


def test_failed_call_saves_nothing(db):
    """One transaction per call: an error part-way leaves no half-saved settings or log lines."""
    import pytest
    repo = Repository(**db)
    bad = SupplierSettings.model_construct(supplier="B", holding_days="not a number", moq=0, lead_time_days=None,
                                           order_cycle_weeks=4)   # skips validation, so the database refuses it
    with pytest.raises(Exception):
        repo.save_settings([S("A", 3), bad])
    assert repo.get_settings() == {} and repo.get_settings_log() == []
