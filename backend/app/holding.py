"""Holding-based order calculation: buffer, target, required and order quantity per SKU."""
import calendar
import math
from datetime import date, timedelta

from app.models import (DAYS_PER_MONTH, DEFAULT_ORDER_CYCLE_WEEKS, ActualSales, DemandValue, HoldingPlan, MonthPlan, OrderLine,
                        ParsedInput, SkuInput, SkuResult, SkuStatus, SupplierSettings)
from app.cities import CITIES
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


def _status(holding_days: float | None, valid_count: int, order: int | None) -> SkuStatus:
    if holding_days is None:
        return SkuStatus.HOLDING_NOT_SET
    if valid_count == 0:
        return SkuStatus.NO_DEMAND_DATA
    return SkuStatus.TO_ORDER if order > 0 else SkuStatus.NO_ORDER_NEEDED


def plan_sku(sku: SkuInput, actuals: dict[str, float], actual_months: list[str],
             forecast_months: list[str], holding_days: float | None,
             plan_date: date, moq: float = 0.0, lead_time_days: int | None = None) -> SkuResult:
    """Plan one SKU. MOQ and lead time are the supplier's settings; the SKU's own (old Data sheet)
    moq / lead_time_days fields are never read. The buffer is average monthly sales / 30 x holding days, in
    cartons, and the order demand forecast tops stock up to it (the target)."""
    demand_values = [DemandValue(month=m, source="actual", value=actuals.get(m),
                                 valid=_is_valid(actuals.get(m))) for m in actual_months]
    demand_values += [DemandValue(month=m, source="forecast", value=sku.forecast.get(m),
                                  valid=_is_valid(sku.forecast.get(m))) for m in forecast_months]
    valid = [d.value for d in demand_values if d.valid]
    valid_count = len(valid)
    avg_sales = sum(valid) / valid_count if valid_count else None
    zero_forecast = (any(d.valid for d in demand_values if d.source == "actual")
                     and not any(d.valid for d in demand_values if d.source == "forecast"))

    available = sku.sellable + sku.sit
    stock_cover = available / avg_sales if avg_sales and available >= 0 else None

    buffer = target = required = order_qty = None
    moq_applied = False
    if holding_days is not None:
        buffer = (avg_sales or 0.0) / DAYS_PER_MONTH * holding_days
        target = buffer
        required = _required(target, available, valid_count)
        order_qty, moq_applied = _raise_to_moq(required, moq)
    status = _status(holding_days, valid_count, order_qty)

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
        avg_sales=avg_sales, buffer=buffer, holding_days=holding_days, target=target, required=required,
        order_qty=order_qty, moq_applied=moq_applied, stock_cover_months=stock_cover,
        next_calc_date=next_calc_date, status=status, zero_forecast=zero_forecast, sit_arrivals=sku.sit_arrivals)


PLAN_MONTHS = 12


def monthly_demand(sku: SkuResult, months: list[str]) -> dict[str, float]:
    """Demand per month for the 12-month plan. For now every month is the average monthly sales (0 with no demand
    data); this is the one place a monthly forecast from the database would plug in."""
    return {m: sku.avg_sales or 0.0 for m in months}


def roll_forward(sku: SkuResult, months: list[str]) -> list[MonthPlan]:
    """The order demand forecast: every month tops stock back up to the target (raised to MOQ), and month 1
    is the SKU's planned order. Orders arrive within the month they are placed."""
    demand = monthly_demand(sku, months)
    plan: list[MonthPlan] = []
    opening = sku.available
    for month in months:
        moq_applied = False
        if sku.target is None:
            order = None
        else:
            order, moq_applied = _raise_to_moq(_required(sku.target, opening, sku.valid_count), sku.moq)
        closing = opening + (order or 0) - demand[month]
        plan.append(MonthPlan(month=month, opening=opening, demand=demand[month], order=order,
                              moq_applied=moq_applied, closing=closing))
        opening = closing
    return plan


def order_up_to(sku: SkuResult, cycle_weeks: int) -> float | None:
    """The stock each order tops up to: buffer + average monthly sales × (cycle × 12 ÷ 52 − 1), so just before the
    next order stock is down to the buffer less one month's sales, as with monthly ordering. Never below one
    cycle's sales (average × cycle × 12 ÷ 52), so a holding under 30 days still orders every cycle. None when
    holding is not set."""
    if sku.buffer is None:
        return None
    cycle_sales = (sku.avg_sales or 0.0) * cycle_weeks * 12 / 52
    return max(sku.buffer - (sku.avg_sales or 0.0) + cycle_sales, cycle_sales)


def _days_in(month: str) -> int:
    year, mon = map(int, month.split("-"))
    return calendar.monthrange(year, mon)[1]


def order_dates(plan_date: date, months: list[str], cycle_weeks: int) -> list[date]:
    """The plan date, then every `cycle_weeks` weeks after it, up to the last day of the last plan month."""
    year, mon = map(int, months[-1].split("-"))
    end = date(year, mon, _days_in(months[-1]))
    dates, day = [], plan_date
    while day <= end:
        dates.append(day)
        day += timedelta(weeks=cycle_weeks)
    return dates


def arrival_days(sku: SkuResult, plan_date: date) -> list[tuple[date, float]]:
    """The SKU's SIT by the day it lands, sorted: an arrival dated before the plan date lands on the plan date. A run
    saved before the Stock in Transit file (no arrivals) has all its SIT landing on the plan date."""
    if sku.sit_arrivals is None:
        return [(plan_date, sku.sit)] if sku.sit else []
    by_day: dict[date, float] = {}
    for a in sku.sit_arrivals:
        day = max(a.date, plan_date)
        by_day[day] = by_day.get(day, 0.0) + a.cartons
    return sorted(by_day.items())


def _daily_demand(sku: SkuResult, months: list[str]):
    """day -> that day's demand: its month's demand ÷ the month's days (0 outside the plan months)."""
    demand = monthly_demand(sku, months)

    def daily(day: date) -> float:
        month = f"{day.year:04d}-{day.month:02d}"
        return demand.get(month, 0.0) / _days_in(month)
    return daily


def weekly_order_plan(sku: SkuResult, months: list[str], plan_date: date, cycle_weeks: int) -> list[MonthPlan]:
    """The order plan: an order on the plan date and every `cycle_weeks` weeks after it, each topping stock up
    to `order_up_to` (raised to MOQ). Stock on hand is followed day by day from the plan date, starting at sellable:
    each day its SIT arrivals land, then an order on an order date arrives, then the day's demand (its month's
    demand ÷ the month's days) is used. Each order counts stock on hand plus the SIT still to arrive, so SIT on its
    way is never ordered twice and the orders don't depend on when it lands. Each month shows its arrivals, its
    orders and their total; a month whose days are all before the plan date has no demand and no order."""
    demand = monthly_demand(sku, months)
    level = order_up_to(sku, cycle_weeks)
    planned = order_dates(plan_date, months, cycle_weeks)
    dates = set(planned)
    daily = _daily_demand(sku, months)
    landing = dict(arrival_days(sku, plan_date))
    pending = sum(landing.values())  # SIT not landed yet

    # The floor in `order_up_to` is one cycle at the average month's rate; February's days use more, so each
    # order also covers the actual demand until the next order date, and stock never runs below 0 before it.
    cover = {d: sum(daily(d + timedelta(days=i)) for i in range(7 * cycle_weeks)) for d in planned}
    stock = sku.sellable
    plan: list[MonthPlan] = []
    for month in months:
        year, mon = map(int, month.split("-"))
        days = _days_in(month)
        opening, used, landed, lines, order_month = stock, 0.0, 0.0, [], False
        for d in range(1, days + 1):
            day = date(year, mon, d)
            if day < plan_date:
                continue
            if day in landing:
                stock += landing[day]
                landed += landing[day]
                pending -= landing[day]
            if day in dates:
                order_month = True
                if level is not None:
                    qty, raised = _raise_to_moq(
                        _required(max(level, cover[day]), stock + pending, sku.valid_count), sku.moq)
                    lines.append(OrderLine(date=day, qty=qty, moq_applied=raised))
                    stock += qty
            stock -= demand[month] / days
            used += demand[month] / days
        order = None if level is None else sum(o.qty for o in lines)
        plan.append(MonthPlan(month=month, opening=opening, demand=used, order=order,
                              moq_applied=any(o.moq_applied for o in lines),
                              closing=opening + landed + (order or 0) - used,
                              order_month=order_month, orders=lines, arrivals=landed))
        stock = plan[-1].closing
    return plan


def sit_run_out(sku: SkuResult, months: list[str], plan_date: date) -> tuple[date, date] | None:
    """(the day stock first runs out, the next SIT arrival after it) when sellable stock plus SIT landed so far, with
    no new orders, falls below 0 before the SKU's last arrival; None otherwise, and always None with no demand data
    or no SIT. New orders are left out: one placed now can't arrive before SIT already on its way."""
    arrivals = arrival_days(sku, plan_date)
    if sku.valid_count == 0 or not arrivals:
        return None
    landing = dict(arrivals)
    last = arrivals[-1][0]
    daily = _daily_demand(sku, months)
    stock, day = sku.sellable, plan_date
    while day < last:
        stock += landing.get(day, 0.0)
        stock -= daily(day)
        if stock < -EPS:
            return day, next(d for d, _ in arrivals if d > day)
        day += timedelta(days=1)
    return None


def _attach_order_plan(result: SkuResult, months: list[str], plan_date: date, cycle_weeks: int) -> None:
    """The order plan and its this-month values, next to the forecast-mode ones. This month's order is the one
    placed on the plan date."""
    result.order_cycle_weeks = cycle_weeks
    result.order_plan = weekly_order_plan(result, months, plan_date, cycle_weeks)
    result.plan_order_up_to = order_up_to(result, cycle_weeks)
    if result.plan_order_up_to is not None:
        result.plan_required = _required(result.plan_order_up_to, result.available, result.valid_count)
    first = next((o for m in result.order_plan for o in m.orders), None)
    result.plan_order_qty = None if first is None else first.qty
    result.plan_moq_applied = first is not None and first.moq_applied
    result.plan_status = _status(result.holding_days, result.valid_count, result.plan_order_qty)


def drop_monthly_order_plan(result: HoldingPlan) -> HoldingPlan:
    """The plan without its order plan when it was saved with a cycle in months (its SKUs carry an order plan
    but no weekly cycle), so it shows "Recalculate" like a run saved before the order cycle. Otherwise as is."""
    if not any(s.order_plan is not None and s.order_cycle_weeks is None for s in result.skus):
        return result
    cleared = {"order_plan": None, "plan_order_up_to": None, "plan_required": None, "plan_order_qty": None,
               "plan_moq_applied": False, "plan_status": None}
    return result.model_copy(update={"skus": [s.model_copy(update=cleared) for s in result.skus],
                                     "plan_counts": None})


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
            supplier=s, holding_days=stored.holding_days if stored else None,
            moq=(stored.moq or 0.0) if stored else 0.0, lead_time_days=stored.lead_time_days if stored else None,
            order_cycle_weeks=(stored.order_cycle_weeks or DEFAULT_ORDER_CYCLE_WEEKS) if stored
            else DEFAULT_ORDER_CYCLE_WEEKS)
    skus = []
    for sku, actuals, city in _plan_units(parsed, actual, actual_months, forecast_months):
        result = plan_sku(sku, actuals, actual_months, forecast_months, used[sku.supplier].holding_days, plan_date,
                          moq=used[sku.supplier].moq, lead_time_days=used[sku.supplier].lead_time_days)
        result.city = city
        skus.append(result)
    plan_months = next_months(parsed.mtd_month, PLAN_MONTHS)
    for result in skus:
        result.monthly = roll_forward(result, plan_months)
        _attach_order_plan(result, plan_months, plan_date, used[result.supplier].order_cycle_weeks)
        result.runs_out_on, result.runs_out_arrival = sit_run_out(result, plan_months, plan_date) or (None, None)
    return HoldingPlan(
        plan_date=plan_date, actual_months=actual_months, forecast_months=forecast_months,
        plan_months=plan_months,
        skus=skus,
        settings_used=list(used.values()),
        blocked_suppliers=[s for s in suppliers if used[s].holding_days is None],
        counts=_counts(skus, [r.status for r in skus]), plan_counts=_counts(skus, [r.plan_status for r in skus]))


def _city_sku(sku: SkuInput, city: str) -> SkuInput:
    """The SKU as one city sees it: that city's stock, stock in transit and forecast."""
    c = sku.cities[city]
    return sku.model_copy(update={
        "sellable": c.sellable, "non_sellable": c.non_sellable, "pg_sellable": c.pg_sellable,
        "pdg_sellable": c.pdg_sellable, "pg_non_sellable": c.pg_non_sellable, "pdg_non_sellable": c.pdg_non_sellable,
        "sit": c.sit, "sit_arrivals": c.sit_arrivals, "forecast": c.forecast})


def _city_active(sku: SkuInput, actuals: dict[str, float], actual_months: list[str],
                 forecast_months: list[str]) -> bool:
    """A city gets a plan row when it has something: a sales value above 0 (actual or forecast), stock or SIT."""
    return (any(_is_valid(actuals.get(m)) for m in actual_months)
            or any(_is_valid(sku.forecast.get(m)) for m in forecast_months)
            or sku.sellable != 0 or sku.non_sellable != 0 or sku.sit != 0)


def _plan_units(parsed: ParsedInput, actual: ActualSales, actual_months: list[str],
                forecast_months: list[str]) -> list[tuple[SkuInput, dict[str, float], str | None]]:
    """(SKU input, its actual cartons, city) for each plan row. A run split by city has a row per city with
    something in it (a SKU with nothing anywhere keeps its Yangon row); a run saved before the split has one
    combined row per SKU, city None."""
    units: list[tuple[SkuInput, dict[str, float], str | None]] = []
    for sku in parsed.skus:
        if sku.cities is None or actual.city_cartons is None:
            units.append((sku, actual.cartons.get(sku.sap_code, {}), None))
            continue
        rows = []
        for city in CITIES:
            if city not in sku.cities:
                continue
            city_sku = _city_sku(sku, city)
            actuals = actual.city_cartons.get(city, {}).get(sku.sap_code, {})
            if _city_active(city_sku, actuals, actual_months, forecast_months):
                rows.append((city_sku, actuals, city))
        units.extend(rows or [(_city_sku(sku, "YGN"), actual.city_cartons.get("YGN", {}).get(sku.sap_code, {}), "YGN")])
    return units


def _counts(skus: list[SkuResult], statuses: list[SkuStatus]) -> dict[str, int]:
    counts = {status.value: 0 for status in SkuStatus}
    counts[ZERO_FORECAST_KEY] = sum(r.zero_forecast for r in skus)
    for status in statuses:
        counts[status.value] += 1
    return counts
