from datetime import date, timedelta
import pytest
from app.demand import DemandSeries
from app.engine import plan_sku
from app.models import SkuInput, SupplierSetting, FlagCode

PD = date(2026, 10, 12)
def day(n): return PD + timedelta(days=n)

def run(sellable, sit=0, lt=7, moq=0, shelf=None, reorder=20, target=30, daily=10.0, h=60,
        mtd=0, month_fc=0.0):
    sku = SkuInput(sap_code="1", supplier="S", description="d", packing_size=1, moq=moq,
                   shelf_life_months=shelf, lead_time_days=lt, sellable=sellable,
                   non_sellable=0, sit=sit, mtd_sales=mtd, forecast={"2026-10": 1})
    return plan_sku(sku, SupplierSetting(supplier="S", reorder_days=reorder, target_days=target),
                    DemandSeries(daily=[daily] * h, tail_rate=daily), PD,
                    current_month_forecast=month_fc)

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


def test_flags_lead_time_at_or_above_reorder():
    assert FlagCode.LEAD_TIME_EXCEEDS_REORDER in codes(run(1000, lt=30, reorder=20))
    assert FlagCode.LEAD_TIME_EXCEEDS_REORDER not in codes(run(1000, lt=30, reorder=20, daily=0.0))

def test_flags_excess_and_expiry_risk():
    p = run(1000, shelf=1)                 # 100 days cover > 30*1.5; > 300 sells in 30 days
    assert {FlagCode.EXCESS, FlagCode.EXPIRY_RISK} <= codes(p)
    assert FlagCode.EXCESS not in codes(run(400))   # 40 days <= 45

def test_flags_no_forecast_holding_stock():
    assert FlagCode.NO_FORECAST_HOLDING_STOCK in codes(run(50, daily=0.0))
    assert FlagCode.NO_FORECAST_HOLDING_STOCK not in codes(run(0, daily=0.0))

def test_negative_stock_is_floored_for_flags():
    assert FlagCode.NO_FORECAST_HOLDING_STOCK not in codes(run(-50, daily=0.0))
    assert FlagCode.EXPIRY_RISK not in codes(run(-500, shelf=1))

def test_flags_missing_lead_time():
    assert FlagCode.MISSING_LEAD_TIME in codes(run(50, lt=None))
    assert FlagCode.MISSING_LEAD_TIME in codes(run(50, lt=-3))
    assert FlagCode.MISSING_LEAD_TIME not in codes(run(50, lt=0))

def test_plan_all_uses_defaults_for_new_supplier_and_flags_mtd_above_forecast():
    from app.engine import plan_all
    from tests.helpers import make_workbook
    from app.parsing import parse_input
    parsed = parse_input(make_workbook([["1001","NewCo","X",12,0,6,7,10,0,0,500] + [310]*12]))
    r = plan_all(parsed, {}, parsed.default_plan_date)
    assert r.new_suppliers == ["NewCo"]
    assert r.settings_used[0].reorder_days == 20 and r.settings_used[0].is_default
    assert FlagCode.MTD_ABOVE_FORECAST in {f.code for f in r.skus[0].flags}
    assert r.flag_counts["MTD_ABOVE_FORECAST"] == 1
    # rest of Oct has zero demand, so the 20-day reorder window first exceeds stock (10) on day 1,
    # when it reaches 1 Nov (310/30 = 10.33)
    assert r.skus[0].orders[0].order_date == date(2026, 10, 13)

def test_validate_plan_date_range():
    from app.engine import validate_plan_date
    from app.parsing import parse_input
    from tests.test_parsing import SAMPLE
    parsed = parse_input(SAMPLE.read_bytes())
    validate_plan_date(parsed, date(2026, 10, 12))
    with pytest.raises(ValueError): validate_plan_date(parsed, date(2026, 10, 11))
    validate_plan_date(parsed, date(2026, 10, 31))   # last day of the MTD month
    with pytest.raises(ValueError, match="MTD end"): validate_plan_date(parsed, date(2026, 11, 1))
    with pytest.raises(ValueError): validate_plan_date(parsed, date(2027, 10, 1))


def test_flag_boundaries_do_not_fire():
    # MTD flag: mtd > 0 and mtd > the month forecast (a zero forecast counts as 0)
    assert FlagCode.MTD_ABOVE_FORECAST in codes(run(1000, mtd=101, month_fc=100))
    assert FlagCode.MTD_ABOVE_FORECAST not in codes(run(1000, mtd=100, month_fc=100))
    assert FlagCode.MTD_ABOVE_FORECAST in codes(run(1000, mtd=50, month_fc=0.0))
    assert FlagCode.MTD_ABOVE_FORECAST not in codes(run(1000, mtd=0, month_fc=0.0))
    # expiry risk: shelf 1 month = 30 days, cover = 300 cartons at 10/day
    assert FlagCode.EXPIRY_RISK in codes(run(301, shelf=1))
    assert FlagCode.EXPIRY_RISK not in codes(run(300, shelf=1))
    assert FlagCode.EXPIRY_RISK not in codes(run(200, shelf=1))
    # lead time just below the reorder level
    assert FlagCode.LEAD_TIME_EXCEEDS_REORDER not in codes(run(1000, lt=19, reorder=20))
    assert FlagCode.LEAD_TIME_EXCEEDS_REORDER in codes(run(1000, lt=20, reorder=20))


def test_plan_date_bounds_end_at_mtd_month_end():
    from app.engine import plan_date_bounds
    from app.parsing import parse_input
    from tests.test_parsing import SAMPLE
    assert plan_date_bounds(parse_input(SAMPLE.read_bytes())) == (date(2026, 10, 12), date(2026, 10, 31))


def test_plan_date_bounds_when_mtd_ends_on_month_end():
    from app.engine import plan_date_bounds, validate_plan_date
    from app.parsing import parse_input
    from tests.helpers import DEFAULT_HEADERS, make_workbook
    headers = ["Oct'26 MTD Sale (1-31 Oct)" if "MTD" in h else h for h in DEFAULT_HEADERS]
    parsed = parse_input(make_workbook([["1001", "S", "X", 12, 0, 6, 7, 10, 0, 0, 5] + [10] * 12], headers=headers))
    assert plan_date_bounds(parsed) == (date(2026, 11, 1), date(2026, 11, 1))
    validate_plan_date(parsed, date(2026, 11, 1))


def test_plan_date_on_month_boundary_keeps_remaining_month_demand():
    from app.engine import plan_all
    from app.parsing import parse_input
    from tests.helpers import make_workbook
    parsed = parse_input(make_workbook([["1001", "S", "X", 12, 0, 6, 7, 10, 0, 0, 100] + [310] * 12]))
    r = plan_all(parsed, {}, date(2026, 10, 31))
    # Oct forecast 310, MTD 100: the 210 left falls on the single remaining day
    assert r.skus[0].weeks[0].demand == pytest.approx(210 + 6 * 310 / 30)


def test_mtd_above_forecast_flag_with_zero_forecast_in_sample_file():
    from app.engine import plan_all
    from app.parsing import parse_input
    from tests.test_parsing import SAMPLE
    parsed = parse_input(SAMPLE.read_bytes())
    r = plan_all(parsed, {}, parsed.default_plan_date)
    sku = next(s for s in r.skus if s.sap_code == "127904330029")
    assert FlagCode.MTD_ABOVE_FORECAST in {f.code for f in sku.flags}


def test_stockout_message_uses_readable_date():
    p = run(50, lt=14)
    msg = next(f.message for f in p.flags if f.code == FlagCode.STOCKOUT_RISK)
    assert "17 Oct 2026" in msg and "2026-10-17" not in msg
