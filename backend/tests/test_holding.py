from datetime import date

import pytest

from app.holding import order_up_to, plan_date_bounds, plan_sku, roll_forward, validate_plan_date
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
    return plan_sku(sku(**kw), dict(zip(ACT, actuals)), ACT, FC, holding, PD, moq=moq, lead_time_days=lead)


def test_spec_worked_example():
    r = run()
    assert r.buffer == pytest.approx(120) and r.valid_count == 6
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
    r = plan_sku(s, dict(zip(ACT, (100, 120, 110))), ACT, FC, 3, PD, moq=150, lead_time_days=61)
    assert (r.pg_sellable, r.pdg_sellable, r.pg_non_sellable, r.pdg_non_sellable) == (150, 50, 7, 3)
    assert r.sellable == 200
    blank = run()
    assert blank.pg_sellable is None and blank.pdg_non_sellable is None


def test_invalid_values_are_skipped():
    r = run(actuals=(-5, 0, 110))          # -5 and 0 invalid
    assert r.valid_count == 4 and r.buffer == pytest.approx((110 + 130 + 140 + 120) / 4)
    assert [d.valid for d in r.demand_values] == [False, False, True, True, True, True]
    r2 = plan_sku(sku(), {"2026-09": 110}, ACT, FC, 3, PD, moq=150, lead_time_days=61)   # Jul/Aug missing from actuals
    assert r2.demand_values[0].value is None and r2.valid_count == 4


def test_required_rounds_up_and_moq_rules():
    r = run(actuals=(120.1, 120, 120), fc=(120, 120, 120), moq=0)   # buffer 120.0167, target 360.05
    assert r.required == 101 and r.order_qty == 101 and not r.moq_applied
    r0 = run(sellable=500)                                          # available 560 > target 360
    assert r0.required == 0 and r0.order_qty == 0 and not r0.moq_applied
    assert r0.status == SkuStatus.NO_ORDER_NEEDED


def test_holding_not_set_blocks_order_but_shows_buffer():
    r = run(holding=None)
    assert r.status == SkuStatus.HOLDING_NOT_SET
    assert r.target is None and r.required is None and r.order_qty is None
    assert r.buffer == pytest.approx(120) and r.stock_cover_months == pytest.approx(260 / 120)


def test_no_demand_data():
    r = run(actuals=(0, 0, 0), fc=(0, 0, 0))
    assert r.status == SkuStatus.NO_DEMAND_DATA and r.buffer is None
    assert r.target == 0 and r.required == 0 and r.order_qty == 0 and r.stock_cover_months is None
    assert run(actuals=(0, 0, 0), fc=(0, 0, 0), holding=None).status == SkuStatus.HOLDING_NOT_SET


def test_negative_available_without_demand_never_orders():
    r = run(sellable=-20, sit=0, moq=50, actuals=(0, 0, 0), fc=(0, 0, 0))
    assert r.available == -20 and r.status == SkuStatus.NO_DEMAND_DATA
    assert r.target == 0 and r.required == 0 and r.order_qty == 0 and not r.moq_applied
    assert r.stock_cover_months is None


def test_negative_available_with_demand_has_no_cover_but_orders():
    r = run(sellable=-20, sit=0, moq=0)       # buffer 120, target 360, available -20
    assert r.required == 380 and r.order_qty == 380 and r.status == SkuStatus.TO_ORDER
    assert r.stock_cover_months is None
    assert run(sellable=0, sit=0).stock_cover_months == 0     # zero stock is a real 0.0 months


def test_zero_forecast_flag_still_orders():
    r = run(fc=(0, 0, 0))                  # buffer from actuals only = 110
    assert r.zero_forecast and r.buffer == pytest.approx(110) and r.order_qty == 150
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
    # fractional holding: 120 * 2.5 = 300, minus 260 available
    r = run(holding=2.5, moq=0)
    assert r.target == pytest.approx(300) and r.required == 40 and r.holding_months == 2.5
    # zero forecast is flagged even when the holding is missing
    r = run(fc=(0, 0, 0), holding=None)
    assert r.zero_forecast and r.status == SkuStatus.HOLDING_NOT_SET


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
    result = plan_all(parsed, actual, {"Alpha Foods": SupplierSettings(supplier="Alpha Foods", holding_months=2, moq=0)},
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
    r = plan_sku(s, dict(zip(ACT, (100, 120, 110))), ACT, FC, 3, PD, moq=0, lead_time_days=None)
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
    assert result.settings_used == [SupplierSettings(supplier="New Co", holding_months=None, moq=0,
                                                     lead_time_days=None, order_cycle_months=1)]
    assert result.blocked_suppliers == ["New Co"]


def test_plan_all_uses_supplier_settings():
    settings = {"S": SupplierSettings(supplier="S", holding_months=3, moq=150, lead_time_days=61,
                                      order_cycle_months=1)}
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
    settings = {s.supplier: SupplierSettings(supplier=s.supplier, holding_months=2, moq=0, lead_time_days=7)
                for s in parsed.skus}
    result = plan_all(parsed, actual, settings, parsed.default_plan_date)
    assert result.plan_months == MONTHS
    assert all(len(s.monthly) == 12 and s.monthly[0].order == s.order_qty for s in result.skus)


# ---- order plan (order cycle) ----------------------------------------------------------------------

def test_order_plan_small_example():          # spec section 3: buffer 120, holding 3, cycle 3 -> order-up-to 600
    m = roll_forward(run(moq=0), MONTHS, cycle=3)
    assert [p.order for p in m] == [340, 0, 0, 360, 0, 0, 360, 0, 0, 360, 0, 0]
    assert [p.order_month for p in m] == [True, False, False] * 4
    assert m[3].opening == pytest.approx(240) and m[0].closing == pytest.approx(480)


def test_order_plan_cycle_one_is_the_forecast():
    for kw in ({}, {"moq": 0}, {"holding": None}, {"actuals": (0, 0, 0), "fc": (0, 0, 0)},
               {"sellable": -20, "sit": 0}, {"holding": 0.5, "moq": 0}):
        r = run(**kw)
        assert roll_forward(r, MONTHS, cycle=1) == roll_forward(r, MONTHS), kw
        assert all(p.order_month for p in roll_forward(r, MONTHS))


def test_order_plan_cycle_twelve_and_five():
    twelve = roll_forward(run(moq=0), MONTHS, cycle=12)
    assert [p.order_month for p in twelve] == [True] + [False] * 11
    assert twelve[0].order == 120 * 14 - 260 and all(p.order == 0 for p in twelve[1:])
    assert [i for i, p in enumerate(roll_forward(run(moq=0), MONTHS, cycle=5)) if p.order_month] == [0, 5, 10]


def test_order_plan_moq_and_zero_order_month():
    m = roll_forward(run(moq=500), MONTHS, cycle=3)
    assert m[0].order == 500 and m[0].moq_applied and not m[1].moq_applied
    big = roll_forward(run(sellable=1000, sit=0, moq=0), MONTHS, cycle=3)   # 1000 already above 600
    assert big[0].order == 0 and big[0].order_month and not big[0].moq_applied


def test_order_plan_holding_not_set_has_no_orders():
    m = roll_forward(run(holding=None), MONTHS, cycle=3)
    assert all(p.order is None for p in m)
    assert m[-1].closing == pytest.approx(260 - 12 * 120)


def test_order_plan_no_demand_orders_zero():
    m = roll_forward(run(actuals=(0, 0, 0), fc=(0, 0, 0)), MONTHS, cycle=3)
    assert all(p.order == 0 and p.closing == 260 for p in m)


def test_order_up_to():
    assert order_up_to(run(), 3) == pytest.approx(600) and order_up_to(run(), 1) == pytest.approx(360)
    assert order_up_to(run(holding=None), 3) is None
    assert order_up_to(run(actuals=(0, 0, 0), fc=(0, 0, 0)), 3) == 0


def test_plan_status_can_differ_from_forecast_status():
    # available 400 is above the target 360 (forecast: no order) but below the order-up-to 600 (order plan: 200)
    settings = {"S": SupplierSettings(supplier="S", holding_months=3, moq=0, lead_time_days=None,
                                      order_cycle_months=3)}
    result = _plan([sku(supplier="S", sellable=400, sit=0)], settings)
    r = result.skus[0]
    assert r.status == SkuStatus.NO_ORDER_NEEDED and r.order_qty == 0
    assert r.plan_status == SkuStatus.TO_ORDER and r.plan_order_qty == 200 and r.plan_required == 200
    assert r.plan_order_up_to == pytest.approx(600) and not r.plan_moq_applied and r.order_cycle_months == 3
    assert r.order_plan[0].order == 200 and r.monthly == roll_forward(r, MONTHS)
    assert result.plan_counts["TO_ORDER"] == result.counts["TO_ORDER"] + 1
    assert result.plan_counts["NO_ORDER_NEEDED"] == result.counts["NO_ORDER_NEEDED"] - 1


def test_plan_moq_applied_and_blocked_plan_values():
    settings = {"S": SupplierSettings(supplier="S", holding_months=3, moq=500, lead_time_days=None,
                                      order_cycle_months=3),
                "B": SupplierSettings(supplier="B", holding_months=None, moq=0, lead_time_days=None,
                                      order_cycle_months=2)}
    result = _plan([sku(supplier="S", code="A"), sku(supplier="B", code="Z")], settings)
    a, z = result.skus
    assert a.plan_required == 340 and a.plan_order_qty == 500 and a.plan_moq_applied
    assert (z.plan_status, z.plan_order_qty, z.plan_required, z.plan_order_up_to) == (
        SkuStatus.HOLDING_NOT_SET, None, None, None)
    assert z.order_cycle_months == 2 and all(p.order is None for p in z.order_plan)


def test_cycle_one_order_plan_equals_forecast_on_fixture():
    from pathlib import Path
    from app.holding import plan_all
    from app.parsing import parse_input
    from app.sales import actual_cartons, parse_sales
    from app.stock import apply_stock, parse_pdg, parse_pg
    fix = Path(__file__).parent / "fixtures"
    raw = (fix / "sample_input.xlsx").read_bytes()
    parsed = apply_stock(parse_input(raw), parse_pg(raw), parse_pdg(raw))[0]
    actual = actual_cartons(parse_sales((fix / "sales_export.xlsx").read_bytes()), parsed)
    settings = {s.supplier: SupplierSettings(supplier=s.supplier, holding_months=2, moq=8000, lead_time_days=7,
                                             order_cycle_months=1) for s in parsed.skus}
    result = plan_all(parsed, actual, settings, parsed.default_plan_date)
    for s in result.skus:
        assert s.order_plan == s.monthly and s.plan_status == s.status and s.plan_order_qty == s.order_qty
        assert s.plan_required == s.required and s.plan_moq_applied == s.moq_applied
    assert result.plan_counts == result.counts