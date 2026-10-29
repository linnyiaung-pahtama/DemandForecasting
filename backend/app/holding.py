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


def _required(level: float, stock: float, valid_count: int) -> int:
    """Whole cartons to bring stock up to the level. No demand data: 0 whatever the stock (spec section 6),
    even if it is negative."""
    return max(math.ceil(level - stock - EPS), 0) if valid_count else 0


def _raise_to_moq(required: int, moq: float) -> tuple[int, bool]:
    """An order above 0 but below the MOQ is raised to the MOQ. Returns (order, MOQ applied)."""
    if 0 < required < moq:
        return math.ceil(moq - EPS), True
    return required, False


def _status(holding_months: float | None, valid_count: int, order: int | None) -> SkuStatus:
    if holding_months is None:
        return SkuStatus.HOLDING_NOT_SET
    if valid_count == 0:
        return SkuStatus.NO_DEMAND_DATA
    return SkuStatus.TO_ORDER if order > 0 else SkuStatus.NO_ORDER_NEEDED


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
        required = _required(target, available, valid_count)
        order_qty, moq_applied = _raise_to_moq(required, moq)
    status = _status(holding_months, valid_count, order_qty)

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


def order_up_to(sku: SkuResult, cycle: int) -> float | None:
    """The stock an order month tops up to: enough that no month until the next order starts below the
    holding, i.e. buffer × (holding + cycle − 1). Cycle 1 gives the target. None when holding is not set."""
    if sku.holding_months is None:
        return None
    return (sku.buffer or 0.0) * (sku.holding_months + cycle - 1)


def roll_forward(sku: SkuResult, months: list[str], cycle: int = 1) -> list[MonthPlan]:
    """Order every `cycle` months, starting with month 1, topping stock up to `order_up_to` (raised to MOQ);
    order nothing in the months between. Cycle 1 is the order demand forecast: every month tops stock back
    up to the target, and month 1 is the SKU's planned order. Orders arrive within the month they are placed."""
    demand = monthly_demand(sku, months)
    level = order_up_to(sku, cycle)
    plan: list[MonthPlan] = []
    opening = sku.available
    for i, month in enumerate(months):
        order_month = i % cycle == 0
        moq_applied = False
        if level is None:
            order = None
        elif not order_month:
            order = 0
        else:
            order, moq_applied = _raise_to_moq(_required(level, opening, sku.valid_count), sku.moq)
        closing = opening + (order or 0) - demand[month]
        plan.append(MonthPlan(month=month, opening=opening, demand=demand[month], order=order,
                              moq_applied=moq_applied, closing=closing, order_month=order_month))
        opening = closing
    return plan


def _attach_order_plan(result: SkuResult, months: list[str], cycle: int) -> None:
    """The order plan and its this-month values, next to the forecast-mode ones."""
    result.order_cycle_months = cycle
    result.order_plan = roll_forward(result, months, cycle)
    result.plan_order_up_to = order_up_to(result, cycle)
    if result.plan_order_up_to is not None:
        result.plan_required = _required(result.plan_order_up_to, result.available, result.valid_count)
    result.plan_order_qty = result.order_plan[0].order
    result.plan_moq_applied = result.order_plan[0].moq_applied
    result.plan_status = _status(result.holding_months, result.valid_count, result.plan_order_qty)


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
        _attach_order_plan(result, plan_months, used[result.supplier].order_cycle_months)
    return HoldingPlan(
        plan_date=plan_date, actual_months=actual_months, forecast_months=forecast_months,
        plan_months=plan_months,
        skus=skus,
        settings_used=list(used.values()),
        blocked_suppliers=[s for s in suppliers if used[s].holding_months is None],
        counts=_counts(skus, [r.status for r in skus]), plan_counts=_counts(skus, [r.plan_status for r in skus]))


def _counts(skus: list[SkuResult], statuses: list[SkuStatus]) -> dict[str, int]:
    counts = {status.value: 0 for status in SkuStatus}
    counts[ZERO_FORECAST_KEY] = sum(r.zero_forecast for r in skus)
    for status in statuses:
        counts[status.value] += 1
    return counts
