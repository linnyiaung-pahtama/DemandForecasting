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


def _plan(supplier, sap, order_days, qtys, lead=7):
    from datetime import timedelta
    from app.models import OrderReason, PlannedOrder, SkuPlan
    pd = date(2026, 10, 12)
    reason = OrderReason(on_hand=0, on_order=0, inventory_position=0, stock_at_arrival=0,
                         reorder_qty=0, target_qty=0, raw_qty=0, moq_applied=False,
                         shelf_life_cap=None, cap_applied=False)
    orders = [PlannedOrder(order_date=pd + timedelta(days=d), arrival_date=pd + timedelta(days=d + lead),
                           qty=q, reason=reason) for d, q in zip(order_days, qtys)]
    return SkuPlan(sap_code=sap, supplier=supplier, description="d", lead_time_days=lead, moq=0,
                   shelf_life_months=None, sellable=0, non_sellable=0, sit=0, starting_stock=0,
                   days_of_cover=None, total_forecast=0, orders=orders, weeks=[], flags=[],
                   stockout_days=0, stockout_qty=0, first_stockout_date=None)


def test_summary_sorting_window_boundary_and_cartons():
    from app.models import PlanResult
    pd = date(2026, 10, 12)
    # Orders are given as day offsets from plan date 12 Oct. Window of 4 weeks -> cutoff day 28
    # (order_date < day 28), window of 2 weeks -> cutoff day 14.
    skus = [
        _plan("A", "A1", [3, 28], [10, 7]),   # day 3 in both windows; day 28 is exactly the 4-week cutoff
        _plan("A", "A2", [27], [5]),          # day 27: in the 4-week window, out of the 2-week one
        _plan("B", "B1", [28], [40]),         # only order is at the 4-week cutoff -> never in window
        _plan("C", "C1", [], []),             # no orders at all
        _plan("D", "D1", [1], [3]),           # earliest of all suppliers
        _plan("E", "E1", [3], [2]),           # same earliest date as A -> name breaks the tie
    ]
    settings = [SupplierSetting(supplier=s, reorder_days=20, target_days=30) for s in "CBEAD"]
    result = PlanResult(plan_date=pd, skus=skus, settings_used=settings, new_suppliers=[], flag_counts={})

    # 4 weeks: A = A1 day 3 (10) + A2 day 27 (5) = 15 cartons, 2 SKUs (A1's day-28 order excluded);
    #          B = 0 in window, but earliest is still day 28 (12 Oct + 28 days = 9 Nov);
    #          D = 3, E = 2, C = nothing at all.
    s4 = summarize_suppliers(result, window_weeks=4)
    assert [x.supplier for x in s4] == ["D", "A", "E", "B", "C"]   # days 1, 3, 3, 28, None
    by4 = {x.supplier: x for x in s4}
    assert (by4["A"].skus_to_order, by4["A"].cartons_in_window) == (2, 15)
    assert (by4["B"].skus_to_order, by4["B"].cartons_in_window) == (0, 0)
    assert by4["B"].earliest_order_date == date(2026, 11, 9)       # outside the window, still reported
    assert (by4["D"].skus_to_order, by4["D"].cartons_in_window) == (1, 3)
    assert (by4["E"].skus_to_order, by4["E"].cartons_in_window) == (1, 2)
    assert by4["C"].earliest_order_date is None and by4["C"].cartons_in_window == 0
    assert by4["A"].earliest_order_date == date(2026, 10, 15)

    # 2 weeks: A = A1 day 3 only = 10 cartons, 1 SKU (A2 day 27 now outside); other suppliers unchanged.
    s2 = summarize_suppliers(result, window_weeks=2)
    by2 = {x.supplier: x for x in s2}
    assert (by2["A"].skus_to_order, by2["A"].cartons_in_window) == (1, 10)
    assert by2["A"].earliest_order_date == date(2026, 10, 15)
    assert (by2["D"].cartons_in_window, by2["E"].cartons_in_window) == (3, 2)
    assert [x.supplier for x in s2] == ["D", "A", "E", "B", "C"]
