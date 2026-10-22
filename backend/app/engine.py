"""Per-SKU reorder simulation: when to order, how much, and the weekly projection."""
import math
from datetime import date, timedelta

from app.demand import DemandSeries
from app.models import (Flag, FlagCode, OrderReason, PlannedOrder, SkuInput, SkuPlan,
                        SupplierSetting, WeekProjection)

EPS = 1e-9


def plan_sku(sku: SkuInput, setting: SupplierSetting, demand: DemandSeries,
             plan_date: date, current_month_forecast: float = 0.0) -> SkuPlan:
    lead = sku.lead_time_days
    shelf_days = round(sku.shelf_life_months * 365 / 12) if sku.shelf_life_months else None
    starting_stock = sku.sellable + sku.sit

    on_hand = starting_stock
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
        if lead is not None and position < reorder_qty:
            target_qty = demand.cover_qty(d, setting.target_days)
            raw = target_qty - position
            qty = math.ceil(raw - EPS)
            moq_applied = sku.moq > 0 and qty < sku.moq
            qty = max(qty, math.ceil(sku.moq))
            cap: float | None = None
            cap_applied = False
            if shelf_days:
                at_arrival = max(position - demand.cover_qty(d, lead), 0.0)
                cap = max(demand.cover_qty(d + lead, shelf_days) - at_arrival, 0.0)
                if qty > cap + EPS:
                    if sku.moq > 0 and sku.moq > cap:
                        qty = math.ceil(sku.moq)  # MOQ wins; flagged below
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
                        inventory_position=position, reorder_qty=reorder_qty,
                        target_qty=target_qty, raw_qty=raw, moq_applied=moq_applied,
                        shelf_life_cap=cap, cap_applied=cap_applied)))
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
                          message="Order today: stock will not last through the lead time."))
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

    return SkuPlan(
        sap_code=sku.sap_code, supplier=sku.supplier, description=sku.description,
        lead_time_days=lead, moq=sku.moq, shelf_life_months=sku.shelf_life_months,
        sellable=sku.sellable, non_sellable=sku.non_sellable, sit=sku.sit,
        starting_stock=starting_stock,
        days_of_cover=demand.days_of_cover(0, starting_stock),
        total_forecast=sum(demand.daily), orders=orders, weeks=weeks, flags=flags,
        stockout_days=stockout_days, stockout_qty=stockout_qty,
        first_stockout_date=first_stockout_date)
