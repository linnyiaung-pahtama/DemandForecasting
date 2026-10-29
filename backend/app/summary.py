"""Per-supplier roll-up of a holding plan."""
from app.models import HoldingPlan, SkuResult, SkuStatus, SupplierSummary


def summarize_suppliers(result: HoldingPlan) -> list[SupplierSummary]:
    summaries: list[SupplierSummary] = []
    for setting in result.settings_used:
        skus = [s for s in result.skus if s.supplier == setting.supplier]
        summaries.append(SupplierSummary(
            supplier=setting.supplier, holding_months=setting.holding_months, sku_count=len(skus),
            skus_to_order=sum(1 for s in skus if s.status == SkuStatus.TO_ORDER),
            total_order_qty=sum(s.order_qty or 0 for s in skus),
            blocked_skus=sum(1 for s in skus if s.status == SkuStatus.HOLDING_NOT_SET),
            no_demand_skus=sum(1 for s in skus if s.status == SkuStatus.NO_DEMAND_DATA),
            zero_forecast_skus=sum(1 for s in skus if s.zero_forecast),
            moq=setting.moq, lead_time_days=setting.lead_time_days,
            **_monthly_totals(skus, len(result.plan_months), blocked=setting.holding_months is None)))
    summaries.sort(key=lambda x: (-x.total_order_qty, x.supplier))
    return summaries


def _monthly_totals(skus: list[SkuResult], months: int, blocked: bool) -> dict:
    """Orders per plan month summed over the supplier's SKUs. Blank (None) when nothing was calculated:
    the supplier's holding is not set, or the run was saved before the 12-month plan."""
    if blocked or not months or any(s.monthly is None for s in skus):
        return {"monthly_order_qty": None, "twelve_month_total": None}
    totals = [sum(s.monthly[i].order or 0 for s in skus) for i in range(months)]
    return {"monthly_order_qty": totals, "twelve_month_total": sum(totals)}