"""Per-supplier roll-up of a plan result."""
from datetime import date, timedelta

from app.models import PlanResult, SupplierSummary


def summarize_suppliers(result: PlanResult, window_weeks: int = 4) -> list[SupplierSummary]:
    cutoff = result.plan_date + timedelta(days=7 * window_weeks)
    summaries: list[SupplierSummary] = []
    for setting in result.settings_used:
        skus = [s for s in result.skus if s.supplier == setting.supplier]
        in_window = [(s, [o for o in s.orders if o.order_date < cutoff]) for s in skus]
        flag_counts: dict[str, int] = {}
        for s in skus:
            for code in {f.code for f in s.flags}:
                flag_counts[code.value] = flag_counts.get(code.value, 0) + 1
        order_dates = [o.order_date for _, os_ in in_window for o in os_]
        leads = [s.lead_time_days for s in skus if s.lead_time_days is not None]
        summaries.append(SupplierSummary(
            supplier=setting.supplier, reorder_days=setting.reorder_days,
            target_days=setting.target_days, is_default=setting.is_default,
            sku_count=len(skus),
            skus_to_order=sum(1 for _, os_ in in_window if os_),
            cartons_in_window=sum(o.qty for _, os_ in in_window for o in os_),
            earliest_order_date=min(order_dates) if order_dates else None,
            flag_counts=flag_counts,
            max_lead_time_days=max(leads) if leads else None))
    summaries.sort(key=lambda x: (x.earliest_order_date or date.max, x.supplier))
    return summaries
