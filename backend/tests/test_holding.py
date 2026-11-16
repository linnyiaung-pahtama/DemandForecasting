import math
from datetime import date

import pytest

from app.holding import (drop_monthly_order_plan, order_dates, order_up_to, plan_date_bounds, plan_sku,
                         roll_forward, validate_plan_date, weekly_order_plan)
from app.months import next_months
from app.models import ActualSales, SkuInput, SkuStatus, SupplierSettings

ACT = ["2026-07", "2026-08", "2026-09"]; FC = ["2026-10", "2026-11", "2026-12"]
PD = date(2026, 10, 14)


def sku(sellable=200, sit=60, fc=(130, 140, 120), supplier="Alpha Foods", code="N1"):
    # MOQ and lead time come from supplier settings, so the SKU's own (old Data sheet) fields stay empty
    return SkuInput(sap_code=code, supplier=supplier, description="Noodles", packing_size=10,
                    moq=0, shelf_life_months=None, lead_time_days=None, sellable=sellable,
                    non_sellable=0, sit=sit, mtd_sales=0, forecast=dict(zip(FC, fc)))


def run(actuals=(100, 120, 110), holding=3, moq=150, lead=61, **kw):
    """`holding` is in months for readability; the SKU is planned with holding x 30 days."""
    days = None if holding is None else holding * 30
    return plan_sku(sku(**kw), dict(zip(ACT, actuals)), ACT, FC, days, PD, moq=moq, lead_time_days=lead)


def test_spec_worked_example():
    r = run()
    assert r.avg_sales == pytest.approx(120) and r.valid_count == 6
    assert r.holding_days == 90 and r.buffer == pytest.approx(120 / 30 * 90)   # 360 cartons
    assert r.target == pytest.approx(360) and r.available == pytest.approx(260)
    assert r.required == 100 and r.order_qty == 150 and r.moq_applied
    assert r.stock_cover_months == pytest.approx(260 / 120)
    assert r.next_calc_date == date(2026, 12, 14)
    assert r.status == SkuStatus.TO_ORDER and not r.zero_forecast
    assert [d.month for d in r.demand_values] == ACT + FC
    assert [d.source for d in r.demand_values] == ["actual"] * 3 + ["forecast"] * 3


def test_breakdown_is_copied_to_result():
    s = sku(sellable=200)
    s.pg_sellable, s.pdg_sellable, s.pg_non_sellable, s.pdg_non_sellable = 150, 50, 7, 3
    r = plan_sku(s, dict(zip(ACT, (100, 120, 110))), ACT, FC, 90, PD, moq=150, lead_time_days=61)
    assert (r.pg_sellable, r.pdg_sellable, r.pg_non_sellable, r.pdg_non_sellable) == (150, 50, 7, 3)
    assert r.sellable == 200
    blank = run()
    assert blank.pg_sellable is None and blank.pdg_non_sellable is None


def test_invalid_values_are_skipped():
    r = run(actuals=(-5, 0, 110))          # -5 and 0 invalid
    assert r.valid_count == 4 and r.avg_sales == pytest.approx((110 + 130 + 140 + 120) / 4)
    assert [d.valid for d in r.demand_values] == [False, False, True, True, True, True]
    r2 = plan_sku(sku(), {"2026-09": 110}, ACT, FC, 90, PD, moq=150, lead_time_days=61)   # Jul/Aug missing from actuals
    assert r2.demand_values[0].value is None and r2.valid_count == 4


def test_required_rounds_up_and_moq_rules():
    r = run(actuals=(120.1, 120, 120), fc=(120, 120, 120), moq=0)   # average 120.0167, buffer = target 360.05
    assert r.required == 101 and r.order_qty == 101 and not r.moq_applied
    r0 = run(sellable=500)                                          # available 560 > target 360
    assert r0.required == 0 and r0.order_qty == 0 and not r0.moq_applied
    assert r0.status == SkuStatus.NO_ORDER_NEEDED


def test_holding_not_set_blocks_order_but_shows_average():
    r = run(holding=None)
    assert r.status == SkuStatus.HOLDING_NOT_SET
    assert r.target is None and r.required is None and r.order_qty is None and r.buffer is None
    assert r.avg_sales == pytest.approx(120) and r.stock_cover_months == pytest.approx(260 / 120)


def test_no_demand_data():
    r = run(actuals=(0, 0, 0), fc=(0, 0, 0))
    assert r.status == SkuStatus.NO_DEMAND_DATA and r.avg_sales is None and r.buffer == 0
    assert r.target == 0 and r.required == 0 and r.order_qty == 0 and r.stock_cover_months is None
    assert run(actuals=(0, 0, 0), fc=(0, 0, 0), holding=None).status == SkuStatus.HOLDING_NOT_SET


def test_negative_available_without_demand_never_orders():
    r = run(sellable=-20, sit=0, moq=50, actuals=(0, 0, 0), fc=(0, 0, 0))
    assert r.available == -20 and r.status == SkuStatus.NO_DEMAND_DATA
    assert r.target == 0 and r.required == 0 and r.order_qty == 0 and not r.moq_applied
    assert r.stock_cover_months is None


def test_negative_available_with_demand_has_no_cover_but_orders():
    r = run(sellable=-20, sit=0, moq=0)       # average 120, buffer = target 360, available -20
    assert r.required == 380 and r.order_qty == 380 and r.status == SkuStatus.TO_ORDER
    assert r.stock_cover_months is None
    assert run(sellable=0, sit=0).stock_cover_months == 0     # zero stock is a real 0.0 months


def test_zero_forecast_flag_still_orders():
    r = run(fc=(0, 0, 0))                  # average from actuals only = 110
    assert r.zero_forecast and r.avg_sales == pytest.approx(110) and r.order_qty == 150
    assert not run(actuals=(0, 0, 0), fc=(0, 0, 0)).zero_forecast   # no valid actuals either


def test_missing_lead_time_has_no_next_date():
    assert run(lead=None).next_calc_date is None
    assert run(lead=-3).next_calc_date is None


def test_huge_lead_time_does_not_crash():
    r = run(lead=4_000_000)
    assert r.next_calc_date is None and r.order_qty == 150


def test_boundaries_and_fractional_holding():
    # required == MOQ is not "MOQ applied"
    r = run(moq=100)
    assert r.required == 100 and r.order_qty == 100 and not r.moq_applied
    # target - available exactly 100
    r = run(sellable=200, sit=60, moq=0)
    assert r.target - r.available == pytest.approx(100) and r.required == 100
    # 75 days: 120 / 30 * 75 = 300, minus 260 available
    r = run(holding=2.5, moq=0)
    assert r.target == pytest.approx(300) and r.required == 40 and r.holding_days == 75
    # zero forecast is flagged even when the holding is missing
    r = run(fc=(0, 0, 0), holding=None)
    assert r.zero_forecast and r.status == SkuStatus.HOLDING_NOT_SET


def test_saved_month_holding_converts_when_loaded():
    from app.models import SkuResult
    old = run().model_dump(mode="json")   # as saved before holding moved to days: months, buffer = monthly average
    for key in ("holding_days", "avg_sales"):
        old.pop(key)
    old.update(holding_months=3, buffer=120.0)
    r = SkuResult.model_validate(old)
    assert (r.holding_days, r.avg_sales, r.buffer) == (90, 120.0, pytest.approx(360))   # buffer = the old target
    blocked = {**old, "holding_months": None, "target": None}
    assert SkuResult.model_validate(blocked).buffer is None
    assert SupplierSettings.model_validate({"supplier": "A", "holding_months": 2.5}).holding_days == 75
    assert SupplierSettings.model_validate({"supplier": "A", "holding_months": None}).holding_days is None


def test_validate_plan_date_range():
    from app.parsing import parse_input
    from tests.test_parsing import SAMPLE
    parsed = parse_input(SAMPLE.read_bytes())
    validate_plan_date(parsed, date(2026, 10, 12))
    with pytest.raises(ValueError): validate_plan_date(parsed, date(2026, 10, 11))
    validate_plan_date(parsed, date(2026, 10, 31))   # last day of the MTD month
    with pytest.raises(ValueError, match="MTD end"): validate_plan_date(parsed, date(2026, 11, 1))
    with pytest.raises(ValueError): validate_plan_date(parsed, date(2027, 10, 1))


def test_plan_date_bounds_end_at_mtd_month_end():
    from app.parsing import parse_input
    from tests.test_parsing import SAMPLE
    assert plan_date_bounds(parse_input(SAMPLE.read_bytes())) == (date(2026, 10, 12), date(2026, 10, 31))


def test_plan_date_bounds_when_mtd_ends_on_month_end():
    from app.parsing import parse_input
    from tests.helpers import DEFAULT_HEADERS, make_workbook
    headers = ["Oct'26 MTD Sale (1-31 Oct)" if "MTD" in h else h for h in DEFAULT_HEADERS]
    parsed = parse_input(make_workbook([["1001", "S", "X", 12, 0, 6, 7, 10, 0, 0, 5] + [10] * 12], headers=headers))
    assert plan_date_bounds(parsed) == (date(2026, 11, 1), date(2026, 11, 1))
    validate_plan_date(parsed, date(2026, 11, 1))


def test_plan_all_counts_and_zero_forecast():
    from pathlib import Path
    from app.holding import plan_all
    from app.parsing import parse_input
    from app.sales import actual_cartons, parse_sales
    fix = Path(__file__).parent / "fixtures"
    from app.stock import apply_stock, parse_pdg, parse_pg
    raw = (fix / "sample_input.xlsx").read_bytes()
    parsed = apply_stock(parse_input(raw), parse_pg(raw), parse_pdg(raw))[0]
    actual = actual_cartons(parse_sales((fix / "sales_export.xlsx").read_bytes()), parsed)
    result = plan_all(parsed, actual, {}, parsed.default_plan_date)
    assert result.counts["HOLDING_NOT_SET"] == 212
    zero = sum(1 for s in result.skus if s.zero_forecast)
    assert result.counts["ZERO_FORECAST"] == zero and zero > 0
    assert result.forecast_months == ["2026-10", "2026-11", "2026-12"]


def test_plan_all_counts_have_exactly_the_five_keys():
    from app.holding import plan_all
    from app.models import ActualSales
    from app.parsing import parse_input
    from pathlib import Path
    from app.stock import apply_stock, parse_pdg, parse_pg
    raw = (Path(__file__).parent / "fixtures" / "sample_input.xlsx").read_bytes()
    parsed = apply_stock(parse_input(raw), parse_pg(raw), parse_pdg(raw))[0]
    actual = ActualSales(months=ACT, cartons={}, skus_with_sales=0, warnings=[])
    result = plan_all(parsed, actual, {"Alpha Foods": SupplierSettings(supplier="Alpha Foods", holding_days=60, moq=0)},
                      parsed.default_plan_date)
    assert set(result.counts) == {"TO_ORDER", "NO_ORDER_NEEDED", "HOLDING_NOT_SET", "NO_DEMAND_DATA",
                                  "ZERO_FORECAST"}


def test_supplier_moq_raises_each_sku():
    assert (run(moq=150).order_qty, run(moq=150).moq_applied) == (150, True)   # required 100
    assert (run(moq=0).order_qty, run(moq=0).moq_applied) == (100, False)
    r0 = run(sellable=500, moq=150)                                           # required 0
    assert r0.order_qty == 0 and not r0.moq_applied


def test_plan_sku_ignores_moq_and_lead_on_sku_input():
    s = sku().model_copy(update={"moq": 999, "lead_time_days": 5})
    r = plan_sku(s, dict(zip(ACT, (100, 120, 110))), ACT, FC, 90, PD, moq=0, lead_time_days=None)
    assert r.order_qty == 100 and not r.moq_applied and r.moq == 0
    assert r.next_calc_date is None and r.lead_time_days is None


def test_blank_lead_time_does_not_block():
    r = run(lead=None)
    assert r.status == SkuStatus.TO_ORDER and r.next_calc_date is None and r.order_qty == 150


def _plan(skus, settings):
    from app.holding import plan_all
    from app.models import ParsedInput
    parsed = ParsedInput(skus=skus, forecast_months=FC, mtd_month="2026-10", mtd_label="x",
                         mtd_end=date(2026, 10, 11), default_plan_date=date(2026, 10, 12), warnings=[])
    actual = ActualSales(months=ACT, cartons={s.sap_code: dict(zip(ACT, (100, 120, 110))) for s in skus},
                         skus_with_sales=len(skus), warnings=[])
    return plan_all(parsed, actual, settings, PD)


def test_plan_all_supplier_without_settings():
    result = _plan([sku(supplier="New Co")], {})
    r = result.skus[0]
    assert r.status == SkuStatus.HOLDING_NOT_SET and r.next_calc_date is None and r.moq == 0
    assert result.settings_used == [SupplierSettings(supplier="New Co", holding_days=None, moq=0,
                                                     lead_time_days=None, order_cycle_weeks=4)]
    assert result.blocked_suppliers == ["New Co"]


def test_plan_all_uses_supplier_settings():
    settings = {"S": SupplierSettings(supplier="S", holding_days=90, moq=150, lead_time_days=61,
                                      order_cycle_weeks=4)}
    result = _plan([sku(supplier="S", code="A"), sku(supplier="S", code="B")], settings)
    assert all(r.moq == 150 and r.order_qty == 150 and r.moq_applied for r in result.skus)
    assert all(r.lead_time_days == 61 and r.next_calc_date == date(2026, 12, 14) for r in result.skus)
    assert result.settings_used == [settings["S"]] and result.blocked_suppliers == []


# ---- 12-month roll-forward ----------------------------------------------------------------------

MONTHS = next_months("2026-10", 12)


def test_worked_example_rolls_forward():   # spec section 3 table, extended to 12 months
    m = roll_forward(run(), MONTHS)
    assert [p.month for p in m] == MONTHS
    assert [p.order for p in m] == [150, 150, 150, 150, 0, 150, 150, 150, 150, 0, 150, 150]
    assert [p.closing for p in m] == pytest.approx([290, 320, 350, 380, 260, 290, 320, 350, 380, 260, 290, 320])
    assert m[0].opening == 260 and all(p.demand == pytest.approx(120) for p in m)
    assert m[0].moq_applied and m[1].moq_applied and not m[4].moq_applied


def test_moq_zero_orders_the_buffer_after_month_one():
    m = roll_forward(run(moq=0), MONTHS)
    assert [p.order for p in m] == [100] + [120] * 11
    assert all(p.closing == pytest.approx(240) for p in m)


def test_large_moq_orders_once_then_waits():
    # buffer 49/month, holding 2 (target 98), available 0, MOQ 8000
    r = run(actuals=(49, 49, 49), fc=(49, 49, 49), holding=2, moq=8000, sellable=0, sit=0)
    orders = [p.order for p in roll_forward(r, MONTHS)]
    assert orders[0] == 8000 and orders[1:] == [0] * 11


def test_holding_not_set_has_no_orders():
    m = roll_forward(run(holding=None), MONTHS)
    assert all(p.order is None for p in m)
    assert m[-1].closing == pytest.approx(260 - 12 * 120)   # stock runs down


def test_no_demand_orders_zero_and_stock_stays():
    m = roll_forward(run(actuals=(0, 0, 0), fc=(0, 0, 0)), MONTHS)
    assert all(p.order == 0 and p.demand == 0 and p.closing == 260 for p in m)


def test_negative_available_rolls_forward():
    m = roll_forward(run(sellable=-20, sit=0, moq=0), MONTHS)   # target 360
    assert m[0].order == 380 and m[0].closing == pytest.approx(240)
    assert [p.order for p in m[1:]] == [120] * 11 and all(p.order >= 0 for p in m)


def test_plan_all_attaches_twelve_months_matching_todays_order():
    from pathlib import Path
    from app.holding import plan_all
    from app.parsing import parse_input
    from app.sales import actual_cartons, parse_sales
    from app.stock import apply_stock, parse_pdg, parse_pg
    fix = Path(__file__).parent / "fixtures"
    raw = (fix / "sample_input.xlsx").read_bytes()
    parsed = apply_stock(parse_input(raw), parse_pg(raw), parse_pdg(raw))[0]
    actual = actual_cartons(parse_sales((fix / "sales_export.xlsx").read_bytes()), parsed)
    settings = {s.supplier: SupplierSettings(supplier=s.supplier, holding_days=60, moq=0, lead_time_days=7)
                for s in parsed.skus}
    result = plan_all(parsed, actual, settings, parsed.default_plan_date)
    assert result.plan_months == MONTHS
    assert all(len(s.monthly) == 12 and s.monthly[0].order == s.order_qty for s in result.skus)


# ---- order plan (order cycle) ----------------------------------------------------------------------

PD10 = date(2026, 10, 10)


def test_weekly_spec_example():          # spec section 3: buffer 120, holding 3, available 260, cycle 4 weeks
    m = weekly_order_plan(run(moq=0), MONTHS, PD10, 4)
    lines = [(o.date, o.qty) for p in m for o in p.orders]
    assert lines == [(date(2026, 10, 10), 91), (date(2026, 11, 7), 109), (date(2026, 12, 5), 112),
                     (date(2027, 1, 2), 108), (date(2027, 1, 30), 109), (date(2027, 2, 27), 119),
                     (date(2027, 3, 27), 109), (date(2027, 4, 24), 111), (date(2027, 5, 22), 110),
                     (date(2027, 6, 19), 110), (date(2027, 7, 17), 110), (date(2027, 8, 14), 109),
                     (date(2027, 9, 11), 109)]
    assert [p.month for p in m] == MONTHS
    assert [p.order for p in m] == [91, 109, 112, 217, 119, 109, 111, 110, 110, 110, 109, 109]
    # stock on hand starts at sellable 200; the SIT (60, an older-style SKU without arrivals) lands on the plan date
    assert m[0].opening == 200 and m[0].arrivals == 60 and m[0].demand == pytest.approx(120 * 22 / 31)
    assert [p.closing for p in m] == pytest.approx(
        [265.8387, 254.8387, 246.8387, 343.8387, 342.8387, 331.8387, 322.8387, 312.8387, 302.8387,
         292.8387, 281.8387, 270.8387], abs=1e-3)
    assert all(p.demand == pytest.approx(120) for p in m[1:]) and all(p.order_month for p in m)


def test_weekly_order_up_to_and_floor():
    assert order_up_to(run(), 4) == pytest.approx(120 * (2 + 48 / 52))
    assert order_up_to(run(), 1) == pytest.approx(120 * (2 + 12 / 52))
    assert order_up_to(run(), 52) == pytest.approx(120 * 14)
    assert order_up_to(run(holding=0.5), 2) == pytest.approx(120 * 24 / 52)     # floored at one cycle's demand
    assert order_up_to(run(holding=0.5), 1) == pytest.approx(120 * 12 / 52)
    assert order_up_to(run(holding=2), 4) == pytest.approx(120 * (1 + 48 / 52))  # holding of 1 month or more never floors
    assert order_up_to(run(holding=None), 4) is None
    assert order_up_to(run(actuals=(0, 0, 0), fc=(0, 0, 0)), 4) == 0


def test_weekly_low_holding_still_orders():
    m = weekly_order_plan(run(holding=0.5, moq=0, sellable=0, sit=0), MONTHS, PD10, 2)
    qtys = [o.qty for p in m for o in p.orders]
    assert len(qtys) == 26 and all(q > 0 for q in qtys)
    assert min(p.closing for p in m) >= -1e-9   # stock gets down to about 0 before each order, never below


def test_weekly_floor_holds_through_february():
    # Orders on Mondays (12 Oct + 2 weeks…): 1 Feb and 15 Feb must cover February's higher daily demand (120/28)
    m = weekly_order_plan(run(holding=0.5, moq=0, sellable=0, sit=0), MONTHS, date(2026, 10, 12), 2)
    assert m[4].month == "2027-02" and m[4].closing >= -1e-9
    assert min(p.closing for p in m) >= -1e-9


def test_order_dates_stop_at_month_twelve():
    assert order_dates(PD10, MONTHS, 52) == [PD10]
    d = order_dates(PD10, MONTHS, 4)
    assert len(d) == 13 and d[1] == date(2026, 11, 7) and d[-1] == date(2027, 9, 11)
    assert order_dates(date(2026, 10, 31), MONTHS, 1)[-1] == date(2027, 9, 25)


def test_weekly_plan_date_after_month_one():   # MTD ended 31 Oct: plan date 1 Nov, plan months still from Oct
    m = weekly_order_plan(run(moq=0), MONTHS, date(2026, 11, 1), 4)
    # the SIT (60) lands on the plan date, 1 Nov, so October closes at sellable stock (200)
    assert (m[0].demand, m[0].order, m[0].order_month, m[0].orders, m[0].closing) == (0, 0, False, [], 200)
    assert m[1].orders[0].date == date(2026, 11, 1) and m[1].opening == 200 and m[1].arrivals == 60
    assert m[1].orders[0].qty == math.ceil(120 * (2 + 48 / 52) - 260)


def test_weekly_february_uses_its_own_days():
    feb = weekly_order_plan(run(moq=0), MONTHS, PD10, 4)[4]
    assert feb.month == "2027-02" and feb.demand == pytest.approx(120)   # 28 days of 120/28


def test_weekly_month_totals_match_lines():
    for kw, cycle in (({"moq": 0}, 3), ({"moq": 150}, 3), ({"moq": 500}, 2), ({"sellable": -20, "sit": 0}, 4)):
        for p in weekly_order_plan(run(**kw), MONTHS, PD10, cycle):
            assert p.order == sum(o.qty for o in p.orders), kw
            assert p.moq_applied == any(o.moq_applied for o in p.orders), kw
            assert p.order_month == bool(p.orders), kw
            assert p.closing == pytest.approx(p.opening + p.arrivals + p.order - p.demand), kw
    m = weekly_order_plan(run(moq=500), MONTHS, PD10, 4)
    assert m[0].orders[0].qty == 500 and m[0].orders[0].moq_applied and m[0].moq_applied


def test_weekly_holding_not_set_and_no_demand():
    blocked = weekly_order_plan(run(holding=None), MONTHS, PD10, 4)
    assert all(p.order is None and p.orders == [] for p in blocked) and all(p.order_month for p in blocked)
    assert blocked[-1].closing == pytest.approx(260 - 120 * (22 / 31 + 11))
    flat = weekly_order_plan(run(actuals=(0, 0, 0), fc=(0, 0, 0)), MONTHS, PD10, 4)
    assert all(p.order == 0 and p.closing == 260 for p in flat)


def test_forecast_roll_forward_has_no_order_lines():
    assert all(p.orders == [] and p.order_month for p in roll_forward(run(), MONTHS))


def test_plan_status_can_differ_from_forecast_status():
    # available 400 is above the target 360 (forecast: no order) but below the order-up-to
    # 120 × (3 − 1 + 26 × 12 ÷ 52) = 960 of a 26-week cycle (order plan: 560 on the plan date)
    settings = {"S": SupplierSettings(supplier="S", holding_days=90, moq=0, lead_time_days=None,
                                      order_cycle_weeks=26)}
    result = _plan([sku(supplier="S", sellable=400, sit=0)], settings)
    r = result.skus[0]
    assert r.status == SkuStatus.NO_ORDER_NEEDED and r.order_qty == 0
    assert r.plan_status == SkuStatus.TO_ORDER and r.plan_order_qty == 560 and r.plan_required == 560
    assert r.plan_order_up_to == pytest.approx(960) and not r.plan_moq_applied and r.order_cycle_weeks == 26
    assert r.order_plan[0].orders[0].date == PD and r.monthly == roll_forward(r, MONTHS)
    assert result.plan_counts["TO_ORDER"] == result.counts["TO_ORDER"] + 1
    assert result.plan_counts["NO_ORDER_NEEDED"] == result.counts["NO_ORDER_NEEDED"] - 1


def test_plan_moq_applied_and_blocked_plan_values():
    settings = {"S": SupplierSettings(supplier="S", holding_days=90, moq=500, lead_time_days=None,
                                      order_cycle_weeks=4),
                "B": SupplierSettings(supplier="B", holding_days=None, moq=0, lead_time_days=None,
                                      order_cycle_weeks=2)}
    result = _plan([sku(supplier="S", code="A"), sku(supplier="B", code="Z")], settings)
    a, z = result.skus
    assert a.plan_required == 91 and a.plan_order_qty == 500 and a.plan_moq_applied   # ceil(350.77 − 260)
    assert (z.plan_status, z.plan_order_qty, z.plan_required, z.plan_order_up_to, z.plan_moq_applied) == (
        SkuStatus.HOLDING_NOT_SET, None, None, None, False)
    assert z.order_cycle_weeks == 2 and all(p.order is None for p in z.order_plan)


def test_old_month_cycle_run_loses_its_order_plan():
    settings = {"S": SupplierSettings(supplier="S", holding_days=90, moq=0, lead_time_days=None,
                                      order_cycle_weeks=4)}
    current = _plan([sku(supplier="S", code="A"), sku(supplier="S", code="B")], settings)
    assert drop_monthly_order_plan(current) is current
    old = current.model_copy(deep=True)
    for s in old.skus:          # as loaded from a run saved with a months cycle: no order_cycle_weeks
        s.order_cycle_weeks = None
    dropped = drop_monthly_order_plan(old)
    assert all((s.order_plan, s.plan_order_up_to, s.plan_required, s.plan_order_qty, s.plan_status,
                s.plan_moq_applied) == (None, None, None, None, None, False) for s in dropped.skus)
    assert dropped.plan_counts is None and dropped.counts == current.counts
    assert [s.monthly for s in dropped.skus] == [s.monthly for s in current.skus]


def test_fixture_plan_order_is_the_plan_date_order():
    from pathlib import Path
    from app.holding import plan_all
    from app.parsing import parse_input
    from app.sales import actual_cartons, parse_sales
    from app.stock import apply_stock, parse_pdg, parse_pg
    fix = Path(__file__).parent / "fixtures"
    raw = (fix / "sample_input.xlsx").read_bytes()
    parsed = apply_stock(parse_input(raw), parse_pg(raw), parse_pdg(raw))[0]
    actual = actual_cartons(parse_sales((fix / "sales_export.xlsx").read_bytes()), parsed)
    settings = {s.supplier: SupplierSettings(supplier=s.supplier, holding_days=60, moq=8000, lead_time_days=7,
                                             order_cycle_weeks=4) for s in parsed.skus}
    result = plan_all(parsed, actual, settings, parsed.default_plan_date)
    for s in result.skus:
        first = s.order_plan[0].orders[0]
        assert first.date == parsed.default_plan_date and s.order_cycle_weeks == 4
        assert (s.plan_order_qty, s.plan_moq_applied) == (first.qty, first.moq_applied)
        assert s.monthly == roll_forward(s, result.plan_months)
    assert any(s.plan_moq_applied for s in result.skus)


# ---- stock in transit by arrival day ---------------------------------------------------------------

SIT_PD = date(2026, 10, 12)


def plan(avg=120, holding_days=90, sellable=0.0, sit=None, sit_arrivals=(), no_demand=False):
    """One SKU through plan_all (plan date 12 Oct 2026, cycle 4 weeks). `sit_arrivals` is a list of (date, cartons),
    or None for a run saved before the Stock in Transit file (then `sit` lands on the plan date)."""
    from app.holding import plan_all
    from app.models import ParsedInput, SitArrival
    value = 0 if no_demand else avg
    arrivals = None if sit_arrivals is None else [SitArrival(date=d, cartons=c) for d, c in sit_arrivals]
    total = sit if sit is not None else sum(c for _, c in (sit_arrivals or []))
    s = SkuInput(sap_code="T1", supplier="S", description="d", packing_size=1, moq=0, shelf_life_months=None,
                 lead_time_days=None, sellable=sellable, non_sellable=0, sit=total, mtd_sales=0,
                 forecast=dict(zip(FC, (value,) * 3)), sit_arrivals=arrivals)
    parsed = ParsedInput(skus=[s], forecast_months=FC, mtd_month="2026-10", mtd_label="x",
                         mtd_end=date(2026, 10, 11), default_plan_date=SIT_PD, warnings=[])
    actual = ActualSales(months=ACT, cartons={"T1": dict(zip(ACT, (value,) * 3))}, skus_with_sales=1, warnings=[])
    settings = {"S": SupplierSettings(supplier="S", holding_days=holding_days, moq=0, lead_time_days=None,
                                      order_cycle_weeks=4)}
    return plan_all(parsed, actual, settings, SIT_PD).skus[0]


def _lines(r):
    return [(o.date, o.qty) for m in r.order_plan for o in m.orders]


def test_orders_identical_for_any_arrival_timing():
    early = plan(sellable=100, sit_arrivals=[(date(2026, 10, 12), 300)])
    late = plan(sellable=100, sit_arrivals=[(date(2026, 11, 30), 200), (date(2027, 1, 4), 100)])
    mixed = plan(sellable=100, sit_arrivals=[(date(2026, 10, 19), 150), (date(2027, 3, 1), 150)])
    old = plan(sellable=100, sit=300, sit_arrivals=None)
    assert _lines(early) == _lines(late) == _lines(mixed) == _lines(old)
    assert early.plan_order_qty == late.plan_order_qty == old.plan_order_qty


def test_stock_on_hand_and_month_arrivals():
    r = plan(sellable=100, sit_arrivals=[(date(2026, 10, 12), 50), (date(2026, 10, 26), 70), (date(2026, 11, 2), 30)])
    oct_, nov = r.order_plan[0], r.order_plan[1]
    assert oct_.opening == 100 and oct_.arrivals == 120 and nov.arrivals == 30
    assert oct_.closing == pytest.approx(oct_.opening + oct_.arrivals + oct_.order - oct_.demand)
    assert nov.opening == pytest.approx(oct_.closing)
    assert all(m.arrivals == 0 for m in r.order_plan[2:])


def test_late_sit_closings_differ_but_end_the_same():
    early = plan(sellable=100, sit_arrivals=[(date(2026, 10, 12), 300)])
    late = plan(sellable=100, sit_arrivals=[(date(2026, 12, 7), 300)])
    assert late.order_plan[0].closing == pytest.approx(early.order_plan[0].closing - 300)
    assert late.order_plan[2].closing == pytest.approx(early.order_plan[2].closing)


def test_arrival_before_plan_date_lands_on_plan_date():
    r = plan(sellable=0, sit_arrivals=[(date(2026, 10, 5), 40)])
    assert r.order_plan[0].arrivals == 40 and r.order_plan[0].opening == 0


def test_older_run_sit_on_plan_date():
    r = plan(sellable=100, sit=300, sit_arrivals=None)
    assert r.order_plan[0].opening == 100 and r.order_plan[0].arrivals == 300
    assert r.runs_out_on is None and r.sit_arrivals is None


def test_run_out_flagged():
    # avg 30 a month: October's daily demand is 30/31; sellable 5 runs out on 17 Oct, SIT lands on 19 Oct
    r = plan(avg=30, sellable=5, sit_arrivals=[(date(2026, 10, 19), 100)])
    assert (r.runs_out_on, r.runs_out_arrival) == (date(2026, 10, 17), date(2026, 10, 19))


def test_run_out_names_the_next_arrival_not_the_last():
    # 1 carton on 19 Oct isn't enough: stock first goes below 0 on 17 Oct, and the next arrival is 19 Oct
    r = plan(avg=30, sellable=5, sit_arrivals=[(date(2026, 10, 19), 1), (date(2026, 11, 30), 100)])
    assert (r.runs_out_on, r.runs_out_arrival) == (date(2026, 10, 17), date(2026, 10, 19))


def test_run_out_not_flagged_when_sellable_lasts():
    r = plan(avg=30, sellable=50, sit_arrivals=[(date(2026, 10, 19), 100)])
    assert r.runs_out_on is None and r.runs_out_arrival is None


def test_run_out_not_flagged_without_demand_or_sit():
    assert plan(no_demand=True, sellable=-5, sit_arrivals=[(date(2026, 10, 19), 100)]).runs_out_on is None
    assert plan(avg=30, sellable=0, sit_arrivals=[]).runs_out_on is None


def test_forecast_mode_unchanged_by_arrivals():
    r = plan(sellable=100, sit_arrivals=[(date(2026, 11, 30), 300)])
    assert r.available == 400 and r.sit == 300 and all(m.arrivals is None for m in r.monthly)
    assert r.order_qty == plan(sellable=100, sit=300, sit_arrivals=None).order_qty


def test_old_stored_month_plan_loads():
    from app.models import MonthPlan
    m = MonthPlan.model_validate({"month": "2026-10", "opening": 1, "demand": 1, "order": 0, "closing": 0})
    assert m.arrivals is None