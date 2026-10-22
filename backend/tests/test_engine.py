from datetime import date, timedelta
import pytest
from app.demand import DemandSeries
from app.engine import plan_sku
from app.models import SkuInput, SupplierSetting, FlagCode

PD = date(2026, 10, 12)
def day(n): return PD + timedelta(days=n)

def run(sellable, sit=0, lt=7, moq=0, shelf=None, reorder=20, target=30, daily=10.0, h=60):
    sku = SkuInput(sap_code="1", supplier="S", description="d", packing_size=1, moq=moq,
                   shelf_life_months=shelf, lead_time_days=lt, sellable=sellable,
                   non_sellable=0, sit=sit, mtd_sales=0, forecast={"2026-10": 1})
    return plan_sku(sku, SupplierSetting(supplier="S", reorder_days=reorder, target_days=target),
                    DemandSeries(daily=[daily] * h, tail_rate=daily), PD)

def codes(p): return {f.code for f in p.flags}

def test_no_order_when_stock_covers_horizon():
    assert run(1000).orders == []

def test_orders_when_position_drops_below_reorder_level():
    p = run(300)
    o1, o2 = p.orders[0], p.orders[1]
    assert (o1.order_date, o1.arrival_date, o1.qty) == (day(11), day(18), 110)
    assert o1.reason.inventory_position == pytest.approx(190)
    assert o1.reason.reorder_qty == pytest.approx(200) and o1.reason.target_qty == pytest.approx(300)
    assert o1.reason.stock_at_arrival == pytest.approx(120)
    assert (o2.order_date, o2.qty) == (day(22), 110)
    assert p.stockout_days == 0

def test_sit_counts_as_available_stock():
    assert run(100, sit=200).orders[0].order_date == day(11)

def test_order_now_and_lost_sales_when_already_low():
    p = run(50, lt=14)
    o = p.orders[0]
    assert (o.order_date, o.arrival_date, o.qty) == (day(0), day(14), 250)
    assert p.stockout_days == 9 and p.stockout_qty == pytest.approx(90)
    assert p.first_stockout_date == day(5)
    assert {FlagCode.ORDER_NOW, FlagCode.STOCKOUT_RISK} <= codes(p)

def test_moq_is_a_minimum():
    o = run(300, moq=500).orders[0]
    assert o.qty == 500 and o.reason.moq_applied

def test_shelf_life_caps_quantity():
    o = run(300, shelf=1, target=60).orders[0]   # shelf 30 days; cap = 300 - (190-70) = 180
    assert o.qty == 180 and o.reason.cap_applied
    assert o.reason.shelf_life_cap == pytest.approx(180)

def test_moq_above_shelf_life_cap_is_flagged():
    p = run(300, shelf=1, target=60, moq=500)
    o = p.orders[0]
    assert o.qty == 500 and FlagCode.MOQ_EXCEEDS_SHELF_LIFE in codes(p)
    assert o.reason.moq_applied and o.reason.cap_applied

def test_zero_forecast_never_orders():
    p = run(50, daily=0.0)
    assert p.orders == [] and p.days_of_cover is None

def test_missing_lead_time_never_orders():
    assert run(50, lt=None).orders == []

def test_weekly_projection():
    p = run(300)
    w1, w3 = p.weeks[0], p.weeks[2]
    assert (w1.start, w1.end) == (day(0), day(6))
    assert w1.demand == pytest.approx(70) and w1.closing_stock == pytest.approx(230)
    assert w3.arrivals == pytest.approx(110)       # arrival on day 18
    assert len(p.weeks) == 9                       # 60 days -> 8 full weeks + 1 partial

def test_zero_lead_time_delivers_same_day():
    p = run(50, lt=0)
    o = p.orders[0]
    assert o.order_date == o.arrival_date == day(0)
    assert p.stockout_qty == pytest.approx(0)

def test_negative_lead_time_never_orders():
    assert run(50, lt=-3).orders == []

def test_negative_starting_stock_is_floored():
    p = run(-100)
    assert p.stockout_qty == pytest.approx(70)   # order day 0, arrival day 7, 7 days x 10 lost
    assert p.starting_stock == -100
