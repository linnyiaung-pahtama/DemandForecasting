from datetime import date
from pathlib import Path

from app.holding import plan_all
from app.parsing import parse_input
from app.sales import actual_cartons, parse_sales
from app.stock import apply_stock, parse_pdg, parse_pg
from app.summary import summarize_suppliers
from tests.helpers import holding_settings

FIX = Path(__file__).parent / "fixtures"


def _parsed_with_stock():
    raw = (FIX / "sample_input.xlsx").read_bytes()   # the planner's workbook holds the Data and both stock sheets
    return apply_stock(parse_input(raw), parse_pg(raw), parse_pdg(raw))[0]


def test_summary_rolls_up_real_fixtures():
    parsed = _parsed_with_stock()
    actual = actual_cartons(parse_sales((FIX / "sales_export.xlsx").read_bytes()), parsed)
    result = plan_all(parsed, actual, holding_settings({"CFC": 3}, moq=40, lead=7), date(2026, 10, 12))
    summary = summarize_suppliers(result)
    cfc = next(s for s in summary if s.supplier == "CFC")
    cfc_skus = [s for s in result.skus if s.supplier == "CFC"]
    assert cfc.sku_count == 5 and cfc.holding_months == 3 and cfc.blocked_skus == 0
    assert cfc.total_order_qty == sum(s.order_qty for s in cfc_skus)
    assert cfc.skus_to_order == sum(1 for s in cfc_skus if s.order_qty > 0)
    assert all(s.blocked_skus == s.sku_count for s in summary if s.supplier != "CFC")
    assert summary[0].supplier == "CFC"
    assert (cfc.moq, cfc.lead_time_days) == (40, 7)
    other = next(s for s in summary if s.supplier != "CFC")
    assert (other.moq, other.lead_time_days) == (0, None)   # no stored settings: MOQ 0, no lead time


def test_zero_total_suppliers_sort_by_name():
    parsed = _parsed_with_stock()
    actual = actual_cartons(parse_sales((FIX / "sales_export.xlsx").read_bytes()), parsed)
    summary = summarize_suppliers(plan_all(parsed, actual, {}, date(2026, 10, 12)))
    assert all(s.total_order_qty == 0 for s in summary)
    assert [s.supplier for s in summary] == sorted(s.supplier for s in summary)


def test_old_run_settings_used_loads():
    from app.models import HoldingPlan
    plan = HoldingPlan.model_validate({
        "plan_date": "2026-10-12", "actual_months": [], "forecast_months": [], "skus": [],
        "settings_used": [{"supplier": "CFC", "holding_months": 3}], "blocked_suppliers": [],
        "counts": {"TO_ORDER": 0}})
    [s] = summarize_suppliers(plan)
    assert s.supplier == "CFC" and s.holding_months == 3 and s.moq is None and s.lead_time_days is None


def test_supplier_monthly_totals():
    parsed = _parsed_with_stock()
    actual = actual_cartons(parse_sales((FIX / "sales_export.xlsx").read_bytes()), parsed)
    result = plan_all(parsed, actual, holding_settings({"CFC": 3}, moq=0, lead=7), date(2026, 10, 12))
    summary = {s.supplier: s for s in summarize_suppliers(result)}
    cfc_skus = [s for s in result.skus if s.supplier == "CFC"]
    expected = [sum(s.monthly[i].order or 0 for s in cfc_skus) for i in range(12)]
    assert summary["CFC"].monthly_order_qty == expected and len(expected) == 12
    assert summary["CFC"].twelve_month_total == sum(expected)
    blocked = next(s for name, s in summary.items() if name != "CFC")
    # holding not set: nothing was calculated, so no totals (shown as "—"), never 0
    assert blocked.monthly_order_qty is None and blocked.twelve_month_total is None


def _cycle_three_cfc():
    parsed = _parsed_with_stock()
    actual = actual_cartons(parse_sales((FIX / "sales_export.xlsx").read_bytes()), parsed)
    return plan_all(parsed, actual, holding_settings({"CFC": 3}, moq=0, lead=7, cycle=3), date(2026, 10, 12))


def test_summary_order_plan_this_month():
    result = _cycle_three_cfc()
    summary = {s.supplier: s for s in summarize_suppliers(result)}
    cfc, cfc_skus = summary["CFC"], [s for s in result.skus if s.supplier == "CFC"]
    assert cfc.order_cycle_months == 3
    assert cfc.plan_total_order_qty == sum(s.plan_order_qty for s in cfc_skus)
    assert cfc.plan_skus_to_order == sum(1 for s in cfc_skus if s.plan_order_qty > 0)
    assert cfc.plan_total_order_qty > cfc.total_order_qty   # three months' cover instead of one
    months = cfc.plan_monthly_order_qty
    assert [m is not None for m in months] == [True, False, False] * 4
    assert months[0] == cfc.plan_total_order_qty
    assert months[3] == sum(s.order_plan[3].order for s in cfc_skus)
    assert cfc.plan_twelve_month_total == sum(m for m in months if m is not None)


def test_summary_order_plan_blank_for_blocked():
    blocked = next(s for s in summarize_suppliers(_cycle_three_cfc()) if s.supplier != "CFC")
    assert blocked.plan_monthly_order_qty is None and blocked.plan_twelve_month_total is None
    assert (blocked.plan_skus_to_order, blocked.plan_total_order_qty) == (0, 0)   # like the forecast's 0 / 0
    assert blocked.order_cycle_months == 1


def test_summary_old_run_has_blank_order_plan():
    result = _cycle_three_cfc()
    for s in result.skus:      # as a run saved before the order cycle setting
        s.order_plan = s.plan_order_qty = s.plan_status = s.order_cycle_months = None
    result.settings_used = [s.model_copy(update={"order_cycle_months": None}) for s in result.settings_used]
    cfc = next(s for s in summarize_suppliers(result) if s.supplier == "CFC")
    assert (cfc.order_cycle_months, cfc.plan_skus_to_order, cfc.plan_total_order_qty,
            cfc.plan_monthly_order_qty, cfc.plan_twelve_month_total) == (None, None, None, None, None)
    assert cfc.monthly_order_qty is not None


def test_old_run_has_blank_monthly_totals():
    parsed = _parsed_with_stock()
    actual = actual_cartons(parse_sales((FIX / "sales_export.xlsx").read_bytes()), parsed)
    result = plan_all(parsed, actual, holding_settings({"CFC": 3}), date(2026, 10, 12))
    for s in result.skus:
        s.monthly = None          # as a run saved before the 12-month plan
    result.plan_months = []
    cfc = next(s for s in summarize_suppliers(result) if s.supplier == "CFC")
    assert cfc.monthly_order_qty is None and cfc.twelve_month_total is None