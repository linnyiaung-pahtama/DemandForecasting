"""Holding-based order calculation: buffer, target, required and order quantity per SKU."""
import calendar
import math
from datetime import date, timedelta

from app.models import (ActualSales, DemandValue, HoldingPlan, MonthPlan, ParsedInput, SkuInput, SkuResult,
                        SkuStatus, SupplierSettings)
from app.months import next_months

EPS = 1e-9


def _is_valid(value: float | None) -> bool:
    return value is not None and value > 0


def plan_sku(sku: SkuInput, actuals: dict[str, float], actual_months: list[str],
             forecast_months: list[str], holding_months: float | None,
             plan_date: date, moq: float = 0.0, lead_time_days: int | None = None) -> SkuResult:
    """Plan one SKU. MOQ and lead time are the supplier's settings; the SKU's own (old Data sheet)
    moq / lead_time_days fields are never read."""
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
    stock_cover = available / buffer if buffer and available >= 0 else None

    target = required = order_qty = None
    moq_applied = False
    if holding_months is not None:
        target = (buffer or 0.0) * holding_months
        # no demand data: target and order are 0 whatever the stock (spec section 6), even if
        # available is negative
        required = max(math.ceil(target - available - EPS), 0) if valid_count else 0
        order_qty = required
        if 0 < required < moq:
            order_qty = math.ceil(moq - EPS)
            moq_applied = True

    if holding_months is None:
        status = SkuStatus.HOLDING_NOT_SET
    elif valid_count == 0:
        status = SkuStatus.NO_DEMAND_DATA
    elif order_qty > 0:
        status = SkuStatus.TO_ORDER
    else:
        status = SkuStatus.NO_ORDER_NEEDED

    lead = lead_time_days
    next_calc_date = None
    if lead is not None and lead >= 0:
        try:
            next_calc_date = plan_date + timedelta(days=lead)
        except OverflowError:  # absurd lead time: no representable date
            next_calc_date = None

    return SkuResult(
        sap_code=sku.sap_code, supplier=sku.supplier, description=sku.description,
        packing_size=sku.packing_size, lead_time_days=lead, moq=moq, sellable=sku.sellable,
        sit=sku.sit, available=available, pg_sellable=sku.pg_sellable, pdg_sellable=sku.pdg_sellable,
        pg_non_sellable=sku.pg_non_sellable, pdg_non_sellable=sku.pdg_non_sellable,
        demand_values=demand_values, valid_count=valid_count,
        buffer=buffer, holding_months=holding_months, target=target, required=required,
        order_qty=order_qty, moq_applied=moq_applied, stock_cover_months=stock_cover,
        next_calc_date=next_calc_date, status=status, zero_forecast=zero_forecast)


PLAN_MONTHS = 12


def monthly_demand(sku: SkuResult, months: list[str]) -> dict[str, float]:
    """Demand per month for the 12-month plan. For now every month is the buffer (0 with no demand data);
    this is the one place a monthly forecast from the database would plug in."""
    return {m: sku.buffer or 0.0 for m in months}


def roll_forward(sku: SkuResult, months: list[str]) -> list[MonthPlan]:
    """Month 1 is the SKU's planned order; each later month tops stock back up to the target, raised to MOQ.
    Orders are assumed to arrive within the month they are placed."""
    demand = monthly_demand(sku, months)
    plan: list[MonthPlan] = []
    opening = sku.available
    for i, month in enumerate(months):
        moq_applied = False
        if i == 0:
            order, moq_applied = sku.order_qty, sku.moq_applied
        elif sku.holding_months is None:
            order = None
        elif sku.valid_count == 0:
            order = 0
        else:
            order = max(math.ceil((sku.target or 0.0) - opening - EPS), 0)
            if 0 < order < sku.moq:
                order, moq_applied = math.ceil(sku.moq - EPS), True
        closing = opening + (order or 0) - demand[month]
        plan.append(MonthPlan(month=month, opening=opening, demand=demand[month], order=order,
                              moq_applied=moq_applied, closing=closing))
        opening = closing
    return plan


def plan_date_bounds(parsed: ParsedInput) -> tuple[date, date]:
    """Earliest and latest allowed plan date.

    The sales month-to-date ends on the MTD end, so the plan starts the day after it and no later
    than the end of the MTD month (a later start would drop the demand in between). If the MTD ends
    on the last day of its month, the next day is the only allowed date.
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


ZERO_FORECAST_KEY = "ZERO_FORECAST"


def forecast_window(parsed: ParsedInput) -> list[str]:
    """The forecast months used: the MTD month and the next 2."""
    return next_months(parsed.mtd_month, 3)


def plan_all(parsed: ParsedInput, actual: ActualSales, settings: dict[str, SupplierSettings],
             plan_date: date) -> HoldingPlan:
    """Plan every SKU in the Data file with the current supplier settings. A supplier without
    stored settings plans with holding not set, MOQ 0 and no lead time."""
    actual_months = actual.months
    forecast_months = forecast_window(parsed)
    suppliers = list(dict.fromkeys(sku.supplier for sku in parsed.skus))  # first-appearance order
    used = {}
    for s in suppliers:
        stored = settings.get(s)
        used[s] = SupplierSettings(
            supplier=s, holding_months=stored.holding_months if stored else None,
            moq=(stored.moq or 0.0) if stored else 0.0, lead_time_days=stored.lead_time_days if stored else None,
            order_cycle_months=(stored.order_cycle_months or 1) if stored else 1)
    skus = [plan_sku(sku, actual.cartons.get(sku.sap_code, {}), actual_months, forecast_months,
                     used[sku.supplier].holding_months, plan_date, moq=used[sku.supplier].moq,
                     lead_time_days=used[sku.supplier].lead_time_days) for sku in parsed.skus]
    plan_months = next_months(parsed.mtd_month, PLAN_MONTHS)
    for result in skus:
        result.monthly = roll_forward(result, plan_months)
    counts = {status.value: 0 for status in SkuStatus}
    counts[ZERO_FORECAST_KEY] = 0
    for result in skus:
        counts[result.status.value] += 1
        counts[ZERO_FORECAST_KEY] += result.zero_forecast
    return HoldingPlan(
        plan_date=plan_date, actual_months=actual_months, forecast_months=forecast_months,
        plan_months=plan_months,
        skus=skus,
        settings_used=list(used.values()),
        blocked_suppliers=[s for s in suppliers if used[s].holding_months is None], counts=counts)
