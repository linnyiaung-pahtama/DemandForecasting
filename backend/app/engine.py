"""Per-SKU reorder simulation: when to order, how much, and the weekly projection."""
import calendar
import math
from datetime import date, timedelta

from app.config import DEFAULT_REORDER_DAYS, DEFAULT_TARGET_DAYS, EXCESS_FACTOR
from app.demand import DemandSeries, build_demand
from app.models import (Flag, FlagCode, OrderReason, ParsedInput, PlanResult, PlannedOrder,
                        SkuInput, SkuPlan, SupplierSetting, WeekProjection)

EPS = 1e-9


def plan_sku(sku: SkuInput, setting: SupplierSetting, demand: DemandSeries,
             plan_date: date, current_month_forecast: float = 0.0) -> SkuPlan:
    lead = sku.lead_time_days
    shelf_days = round(sku.shelf_life_months * 365 / 12) if sku.shelf_life_months else None
    starting_stock = sku.sellable + sku.sit  # raw sum, kept visible on the plan
    opening_stock = max(starting_stock, 0.0)  # the simulation never starts negative
    can_order = lead is not None and lead >= 0  # missing or negative lead time: no orders

    on_hand = opening_stock
    pipeline: list[tuple[int, float]] = []  # (arrival_day, qty)
    orders: list[PlannedOrder] = []
    flags: list[Flag] = []
    moq_exceeds_shelf = False

    horizon = demand.horizon
    day_demand = [0.0] * horizon
    day_arrivals = [0.0] * horizon
    day_closing = [0.0] * horizon
    day_lost = [0.0] * horizon
    stockout_days = 0
    stockout_qty = 0.0
    first_stockout: int | None = None

    for d in range(horizon):
        due = sum(q for a, q in pipeline if a == d)
        if due:
            pipeline = [(a, q) for a, q in pipeline if a != d]
            on_hand += due
            day_arrivals[d] = due

        on_order = sum(q for _, q in pipeline)
        position = max(on_hand, 0.0) + on_order
        reorder_qty = demand.cover_qty(d, setting.reorder_days)
        if can_order and position < reorder_qty:
            target_qty = demand.cover_qty(d, setting.target_days)
            raw = target_qty - position
            qty = math.ceil(raw - EPS)
            moq_applied = sku.moq > 0 and qty < sku.moq
            qty = max(qty, math.ceil(sku.moq))
            at_arrival = max(position - demand.cover_qty(d, lead), 0.0)
            cap: float | None = None
            cap_applied = False
            if shelf_days:
                cap = max(demand.cover_qty(d + lead, shelf_days) - at_arrival, 0.0)
                if qty > cap + EPS:
                    if sku.moq > 0 and sku.moq > cap:
                        qty = math.ceil(sku.moq)  # MOQ wins; flagged below
                        moq_applied = True
                        cap_applied = True
                        moq_exceeds_shelf = True
                    else:
                        qty = math.floor(cap + EPS)
                        cap_applied = True
            if qty > 0:
                orders.append(PlannedOrder(
                    order_date=plan_date + timedelta(days=d),
                    arrival_date=plan_date + timedelta(days=d + lead),
                    qty=qty,
                    reason=OrderReason(
                        on_hand=max(on_hand, 0.0), on_order=on_order,
                        inventory_position=position, stock_at_arrival=at_arrival, reorder_qty=reorder_qty,
                        target_qty=target_qty, raw_qty=raw, moq_applied=moq_applied,
                        shelf_life_cap=cap, cap_applied=cap_applied)))
                if lead == 0:  # same-day delivery: on hand before today's demand
                    on_hand += qty
                    day_arrivals[d] += qty
                else:
                    pipeline.append((d + lead, float(qty)))

        need = demand.demand(d)
        day_demand[d] = need
        if on_hand >= need:
            on_hand -= need
        else:
            short = need - on_hand
            if short > EPS:
                day_lost[d] = short
                stockout_qty += short
                stockout_days += 1
                if first_stockout is None:
                    first_stockout = d
            on_hand = 0.0
        day_closing[d] = on_hand

    weeks: list[WeekProjection] = []
    for w, start in enumerate(range(0, horizon, 7), start=1):
        end = min(start + 7, horizon)
        weeks.append(WeekProjection(
            week=w,
            start=plan_date + timedelta(days=start),
            end=plan_date + timedelta(days=end - 1),
            demand=sum(day_demand[start:end]),
            arrivals=sum(day_arrivals[start:end]),
            closing_stock=day_closing[end - 1],
            lost=sum(day_lost[start:end]),
            reorder_qty=demand.cover_qty(start, setting.reorder_days),
            target_qty=demand.cover_qty(start, setting.target_days)))

    if any(o.order_date == plan_date for o in orders):
        flags.append(Flag(code=FlagCode.ORDER_NOW,
                          message=("Order today: the inventory position (stock plus on order) is already "
                                 "below the reorder level.")))
    first_stockout_date = (plan_date + timedelta(days=first_stockout)
                           if first_stockout is not None else None)
    if stockout_qty > 0:
        flags.append(Flag(
            code=FlagCode.STOCKOUT_RISK,
            message=(f"Stock runs out on {first_stockout_date.isoformat()}: "
                     f"{stockout_days} days short, about {math.ceil(stockout_qty)} cartons of sales lost.")))
    if moq_exceeds_shelf:
        flags.append(Flag(
            code=FlagCode.MOQ_EXCEEDS_SHELF_LIFE,
            message="The minimum order quantity is more than can be sold within the shelf life."))

    total_forecast = sum(demand.daily)
    days_of_cover = demand.days_of_cover(0, opening_stock)

    if lead is not None and lead >= setting.reorder_days and total_forecast > 0:
        flags.append(Flag(
            code=FlagCode.LEAD_TIME_EXCEEDS_REORDER,
            message=(f"Lead time ({lead} days) is not shorter than the reorder level "
                     f"({setting.reorder_days} days), so this SKU runs out before each order arrives.")))
    if days_of_cover is not None and days_of_cover > setting.target_days * EXCESS_FACTOR:
        flags.append(Flag(
            code=FlagCode.EXCESS,
            message=(f"Stock covers {days_of_cover:.0f} days of sales, more than "
                     f"{EXCESS_FACTOR} x the target of {setting.target_days} days.")))
    if shelf_days and opening_stock > demand.cover_qty(0, shelf_days) + EPS:
        flags.append(Flag(
            code=FlagCode.EXPIRY_RISK,
            message=(f"Current stock is more than the forecast sells within the shelf life "
                     f"({shelf_days} days).")))
    if total_forecast == 0 and opening_stock > 0:
        flags.append(Flag(
            code=FlagCode.NO_FORECAST_HOLDING_STOCK,
            message="No forecast demand, but the SKU is holding stock."))
    if sku.mtd_sales > current_month_forecast > 0:
        flags.append(Flag(
            code=FlagCode.MTD_ABOVE_FORECAST,
            message=(f"Sales so far this month ({sku.mtd_sales:g}) already exceed the month's "
                     f"forecast ({current_month_forecast:g}).")))
    if lead is None or lead < 0:
        flags.append(Flag(
            code=FlagCode.MISSING_LEAD_TIME,
            message="Lead time is missing or invalid, so no orders can be planned for this SKU."))

    return SkuPlan(
        sap_code=sku.sap_code, supplier=sku.supplier, description=sku.description,
        lead_time_days=lead, moq=sku.moq, shelf_life_months=sku.shelf_life_months,
        sellable=sku.sellable, non_sellable=sku.non_sellable, sit=sku.sit,
        starting_stock=starting_stock,
        days_of_cover=days_of_cover,
        total_forecast=total_forecast, orders=orders, weeks=weeks, flags=flags,
        stockout_days=stockout_days, stockout_qty=stockout_qty,
        first_stockout_date=first_stockout_date)


def validate_plan_date(parsed: ParsedInput, plan_date: date) -> None:
    """Plan date must be after the MTD end and within the forecast months."""
    year, mon = (int(p) for p in parsed.forecast_months[-1].split("-"))
    last = date(year, mon, calendar.monthrange(year, mon)[1])
    earliest = parsed.mtd_end + timedelta(days=1)
    if plan_date <= parsed.mtd_end or plan_date > last:
        raise ValueError(
            f"Plan date {plan_date.isoformat()} is outside the allowed range: "
            f"{earliest.isoformat()} to {last.isoformat()}.")


def plan_all(parsed: ParsedInput, settings: dict[str, SupplierSetting],
             plan_date: date) -> PlanResult:
    current_month_key = parsed.mtd_month
    used: dict[str, SupplierSetting] = {}
    new_suppliers: list[str] = []
    skus: list[SkuPlan] = []
    flag_counts: dict[str, int] = {}
    for sku in parsed.skus:
        if sku.supplier not in used:
            setting = settings.get(sku.supplier)
            if setting is None:
                setting = SupplierSetting(supplier=sku.supplier, reorder_days=DEFAULT_REORDER_DAYS,
                                          target_days=DEFAULT_TARGET_DAYS, is_default=True)
                new_suppliers.append(sku.supplier)
            used[sku.supplier] = setting
        demand = build_demand(sku, parsed.forecast_months, parsed.mtd_month, plan_date)
        plan = plan_sku(sku, used[sku.supplier], demand, plan_date,
                        current_month_forecast=sku.forecast.get(current_month_key, 0.0))
        skus.append(plan)
        for code in {f.code for f in plan.flags}:
            flag_counts[code.value] = flag_counts.get(code.value, 0) + 1
    return PlanResult(plan_date=plan_date, skus=skus, settings_used=list(used.values()),
                      new_suppliers=new_suppliers, flag_counts=flag_counts)
