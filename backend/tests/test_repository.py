from app.engine import plan_all
from app.models import SupplierSetting
from app.parsing import parse_input
from app.repository import Repository
from tests.helpers import make_workbook


def test_settings_round_trip_and_defaults_do_not_overwrite(tmp_path):
    repo = Repository(tmp_path / "t.db")
    repo.save_settings([SupplierSetting(supplier="A", reorder_days=40, target_days=60)])
    repo.add_default_settings([SupplierSetting(supplier="A", reorder_days=20, target_days=30, is_default=True),
                               SupplierSetting(supplier="B", reorder_days=20, target_days=30, is_default=True)])
    s = repo.get_settings()
    assert s["A"].reorder_days == 40 and not s["A"].is_default
    assert s["B"].is_default


def test_run_round_trip(tmp_path):
    repo = Repository(tmp_path / "t.db")
    parsed = parse_input(make_workbook([["1","A","x",12,0,6,7,5,0,0,0] + [300]*12]))
    result = plan_all(parsed, {}, parsed.default_plan_date)
    run_id = repo.create_run("in.xlsx", parsed, result)
    rec = repo.get_run(run_id)
    assert rec.file_name == "in.xlsx" and rec.result == result and rec.parsed == parsed
    assert [r.id for r in repo.list_runs()] == [run_id] and repo.latest_run_id() == run_id
    assert repo.get_run(999) is None


def test_update_run_result_and_list_newest_first(tmp_path):
    repo = Repository(tmp_path / "sub" / "t.db")
    parsed = parse_input(make_workbook([["1","A","x",12,0,6,7,5,0,0,0] + [300]*12]))
    result = plan_all(parsed, {}, parsed.default_plan_date)
    first = repo.create_run("a.xlsx", parsed, result)
    second = repo.create_run("b.xlsx", parsed, result)
    assert [r.id for r in repo.list_runs()] == [second, first]
    assert repo.list_runs()[0].sku_count == 1
    changed = plan_all(parsed, {"A": SupplierSetting(supplier="A", reorder_days=5, target_days=9)},
                       parsed.default_plan_date)
    repo.update_run_result(first, changed)
    assert repo.get_run(first).result == changed
    assert repo.get_run(second).result == result
    assert repo.latest_run_id() == second


def test_latest_run_id_empty(tmp_path):
    assert Repository(tmp_path / "t.db").latest_run_id() is None
