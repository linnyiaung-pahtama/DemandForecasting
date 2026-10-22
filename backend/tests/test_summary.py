from datetime import date
from app.engine import plan_all
from app.parsing import parse_input
from app.summary import summarize_suppliers
from app.models import SupplierSetting
from tests.helpers import make_workbook

def test_summary_counts_orders_in_window():
    rows = [["1","A","low",12,0,None,7,5,0,0,0] + [300]*12,     # orders now
            ["2","A","high",12,0,None,7,5000,0,0,0] + [300]*12, # no order within 4 weeks
            ["3","B","low",12,0,None,7,5,0,0,0] + [300]*12]
    parsed = parse_input(make_workbook(rows))
    settings = {"A": SupplierSetting(supplier="A", reorder_days=20, target_days=30)}
    s = summarize_suppliers(plan_all(parsed, settings, parsed.default_plan_date), window_weeks=4)
    a = next(x for x in s if x.supplier == "A")
    assert a.sku_count == 2 and a.skus_to_order == 1
    assert a.earliest_order_date == parsed.default_plan_date
    assert a.max_lead_time_days == 7 and not a.is_default
    assert next(x for x in s if x.supplier == "B").is_default
