from datetime import date
import pytest
from app.demand import build_demand, DemandSeries
from app.models import SkuInput

def sku(mtd, fc):
    return SkuInput(sap_code="1", supplier="S", description="d", packing_size=1, moq=0,
                    shelf_life_months=None, lead_time_days=7, sellable=0, non_sellable=0,
                    sit=0, mtd_sales=mtd, forecast=fc)

FC = {"2026-10": 310, "2026-11": 300}
MONTHS = ["2026-10", "2026-11"]

def test_current_month_spreads_remaining_after_mtd():
    d = build_demand(sku(110, FC), MONTHS, "2026-10", date(2026, 10, 12))
    assert d.horizon == 20 + 30
    assert d.daily[0] == pytest.approx(10) and d.daily[19] == pytest.approx(10)
    assert d.daily[20] == pytest.approx(10)   # Nov 300/30
    assert d.tail_rate == pytest.approx(10)

def test_negative_mtd_treated_as_zero():
    d = build_demand(sku(-5, FC), MONTHS, "2026-10", date(2026, 10, 12))
    assert d.daily[0] == pytest.approx(15.5)

def test_mtd_above_forecast_leaves_zero_for_rest_of_month():
    d = build_demand(sku(400, FC), MONTHS, "2026-10", date(2026, 10, 12))
    assert sum(d.daily[:20]) == 0 and d.daily[20] == pytest.approx(10)

def test_plan_date_in_later_month_drops_earlier_months_and_mtd():
    d = build_demand(sku(110, FC), MONTHS, "2026-10", date(2026, 11, 16))
    assert d.horizon == 15 and d.daily[0] == pytest.approx(10)

def test_cover_qty_uses_tail_rate_beyond_horizon():
    d = DemandSeries(daily=[10.0] * 50, tail_rate=10.0)
    assert d.cover_qty(45, 10) == pytest.approx(100)

def test_days_of_cover():
    d = DemandSeries(daily=[10.0] * 50, tail_rate=10.0)
    assert d.days_of_cover(0, 250) == pytest.approx(25.0)
    assert d.days_of_cover(0, 255) == pytest.approx(25.5)
    assert DemandSeries(daily=[0.0] * 50, tail_rate=0.0).days_of_cover(0, 10) is None
