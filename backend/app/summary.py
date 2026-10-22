"""Per-supplier roll-up of a plan result."""
from datetime import date, timedelta

from app.models import PlanResult, SkuPlan, SupplierSummary


def count_flags(skus: list[SkuPlan]) -> dict[str, int]:
    """Number of SKUs carrying each flag code (keys are the enum values)."""
    counts: dict[str, int] = {}
    for sku in skus:
        for code in {f.code for f in sku.flags}:
            counts[code.value] = counts.get(code.value, 0) + 1
    return counts


def summarize_suppliers(result: PlanResult, window_weeks: int = 4) -> list[SupplierSummary]:
    cutoff = result.plan_date + timedelta(days=7 * window_weeks)
    summaries: list[SupplierSummary] = []
    for setting in result.settings_used:
        skus = [s for s in result.skus if s.supplier == setting.supplier]
        in_window = [[o for o in s.orders if o.order_date < cutoff] for s in skus]
        all_dates = [o.order_date for s in skus for o in s.orders]  # earliest is not window-limited
        leads = [s.lead_time_days for s in skus if s.lead_time_days is not None]
        summaries.append(SupplierSummary(
            supplier=setting.supplier, reorder_days=setting.reorder_days,
            target_days=setting.target_days, is_default=setting.is_default,
            sku_count=len(skus),
            skus_to_order=sum(1 for orders in in_window if orders),
            cartons_in_window=sum(o.qty for orders in in_window for o in orders),
            earliest_order_date=min(all_dates) if all_dates else None,
            flag_counts=count_flags(skus),
            max_lead_time_days=max(leads) if leads else None))
    summaries.sort(key=lambda x: (x.earliest_order_date or date.max, x.supplier))
    return summaries
