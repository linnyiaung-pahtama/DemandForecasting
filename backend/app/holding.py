"""Holding-based order calculation: buffer, target, required and order quantity per SKU."""
import calendar
import math
from datetime import date, timedelta

from app.models import DemandValue, ParsedInput, SkuInput, SkuResult, SkuStatus

EPS = 1e-9


def _is_valid(value: float | None) -> bool:
    return value is not None and value > 0


def plan_sku(sku: SkuInput, actuals: dict[str, float], actual_months: list[str],
             forecast_months: list[str], holding_months: float | None,
             plan_date: date) -> SkuResult:
    demand_values = [DemandValue(month=m, source="actual", value=actuals.get(m),
                                 valid=_is_valid(actuals.get(m))) for m in actual_months]
    demand_values += [DemandValue(month=m, source="forecast", value=sku.forecast.get(m),
                                  valid=_is_valid(sku.forecast.get(m))) for m in forecast_months]
    valid = [d.value for d in demand_values if d.valid]
    valid_count = len(valid)
    buffer = sum(valid) / valid_count if valid_count else None
    zero_forecast = (any(d.valid for d in demand_values if d.source == "actual")
                     and not any(d.valid for d in demand_values if d.source == "forecast"))

    available = sku.sellable + sku.sit
    stock_cover = available / buffer if buffer else None

    target = required = order_qty = None
    moq_applied = False
    if holding_months is not None:
        target = (buffer or 0.0) * holding_months
        required = max(math.ceil(target - available - EPS), 0)
        order_qty = required
        if 0 < required < sku.moq:
            order_qty = math.ceil(sku.moq - EPS)
            moq_applied = True

    if holding_months is None:
        status = SkuStatus.HOLDING_NOT_SET
    elif valid_count == 0:
        status = SkuStatus.NO_DEMAND_DATA
    elif order_qty > 0:
        status = SkuStatus.TO_ORDER
    else:
        status = SkuStatus.NO_ORDER_NEEDED

    lead = sku.lead_time_days
    next_calc_date = plan_date + timedelta(days=lead) if lead is not None and lead >= 0 else None

    return SkuResult(
        sap_code=sku.sap_code, supplier=sku.supplier, description=sku.description,
        packing_size=sku.packing_size, lead_time_days=lead, moq=sku.moq, sellable=sku.sellable,
        sit=sku.sit, available=available, demand_values=demand_values, valid_count=valid_count,
        buffer=buffer, holding_months=holding_months, target=target, required=required,
        order_qty=order_qty, moq_applied=moq_applied, stock_cover_months=stock_cover,
        next_calc_date=next_calc_date, status=status, zero_forecast=zero_forecast)


def plan_date_bounds(parsed: ParsedInput) -> tuple[date, date]:
    """Earliest and latest allowed plan date.

    Stock is as of the MTD end, so the plan starts the day after it and no later than the end of
    the MTD month (a later start would drop the demand in between). If the MTD ends on the last
    day of its month, the next day is the only allowed date.
    """
    earliest = parsed.mtd_end + timedelta(days=1)
    year, mon = parsed.mtd_end.year, parsed.mtd_end.month
    month_end = date(year, mon, calendar.monthrange(year, mon)[1])
    return earliest, max(month_end, earliest)


def validate_plan_date(parsed: ParsedInput, plan_date: date) -> None:
    """Plan date must be after the MTD end and within the MTD month."""
    earliest, last = plan_date_bounds(parsed)
    if plan_date < earliest or plan_date > last:
        raise ValueError(
            f"Plan date {plan_date.isoformat()} is outside the allowed range: "
            f"{earliest.isoformat()} to {last.isoformat()}. Stock figures are as of the MTD end "
            f"({parsed.mtd_end.isoformat()}), so the plan date can be at most the end of that month.")
