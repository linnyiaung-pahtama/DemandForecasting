from datetime import date
from pathlib import Path

from app.holding import plan_all
from app.parsing import parse_input
from app.sales import actual_cartons, parse_sales
from app.summary import summarize_suppliers

FIX = Path(__file__).parent / "fixtures"


def test_summary_rolls_up_real_fixtures():
    parsed = parse_input((FIX / "sample_input.xlsx").read_bytes())
    actual = actual_cartons(parse_sales((FIX / "sales_export.xlsx").read_bytes()), parsed)
    result = plan_all(parsed, actual, {"CFC": 3}, date(2026, 10, 12))
    summary = summarize_suppliers(result)
    cfc = next(s for s in summary if s.supplier == "CFC")
    cfc_skus = [s for s in result.skus if s.supplier == "CFC"]
    assert cfc.sku_count == 5 and cfc.holding_months == 3 and cfc.blocked_skus == 0
    assert cfc.total_order_qty == sum(s.order_qty for s in cfc_skus)
    assert cfc.skus_to_order == sum(1 for s in cfc_skus if s.order_qty > 0)
    assert all(s.blocked_skus == s.sku_count for s in summary if s.supplier != "CFC")
    assert summary[0].supplier == "CFC"


def test_zero_total_suppliers_sort_by_name():
    parsed = parse_input((FIX / "sample_input.xlsx").read_bytes())
    actual = actual_cartons(parse_sales((FIX / "sales_export.xlsx").read_bytes()), parsed)
    summary = summarize_suppliers(plan_all(parsed, actual, {}, date(2026, 10, 12)))
    assert all(s.total_order_qty == 0 for s in summary)
    assert [s.supplier for s in summary] == sorted(s.supplier for s in summary)
