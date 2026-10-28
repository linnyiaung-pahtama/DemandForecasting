from datetime import date

import pytest

from app.holding import plan_date_bounds, plan_sku, validate_plan_date
from app.models import SkuInput, SkuStatus

ACT = ["2026-07", "2026-08", "2026-09"]; FC = ["2026-10", "2026-11", "2026-12"]
PD = date(2026, 10, 14)


def sku(sellable=200, sit=60, moq=150, lead=61, fc=(130, 140, 120)):
    return SkuInput(sap_code="N1", supplier="Alpha Foods", description="Noodles", packing_size=10,
                    moq=moq, shelf_life_months=None, lead_time_days=lead, sellable=sellable,
                    non_sellable=0, sit=sit, mtd_sales=0, forecast=dict(zip(FC, fc)))


def run(actuals=(100, 120, 110), holding=3, **kw):
    return plan_sku(sku(**kw), dict(zip(ACT, actuals)), ACT, FC, holding, PD)


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


def test_invalid_values_are_skipped():
    r = run(actuals=(-5, 0, 110))          # -5 and 0 invalid
    assert r.valid_count == 4 and r.buffer == pytest.approx((110 + 130 + 140 + 120) / 4)
    assert [d.valid for d in r.demand_values] == [False, False, True, True, True, True]
    r2 = plan_sku(sku(), {"2026-09": 110}, ACT, FC, 3, PD)   # Jul/Aug missing from actuals
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
    parsed = parse_input((fix / "sample_input.xlsx").read_bytes())
    actual = actual_cartons(parse_sales((fix / "sales_export.xlsx").read_bytes()), parsed)
    result = plan_all(parsed, actual, {}, parsed.default_plan_date)
    assert result.counts["HOLDING_NOT_SET"] == 212
    zero = sum(1 for s in result.skus if s.zero_forecast)
    assert result.counts["ZERO_FORECAST"] == zero and zero > 0
    assert result.forecast_months == ["2026-10", "2026-11", "2026-12"]
