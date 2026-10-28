"""Per-supplier roll-up of a holding plan."""
from app.models import HoldingPlan, SkuStatus, SupplierSummary


def summarize_suppliers(result: HoldingPlan) -> list[SupplierSummary]:
    summaries: list[SupplierSummary] = []
    for setting in result.settings_used:
        skus = [s for s in result.skus if s.supplier == setting.supplier]
        leads = [s.lead_time_days for s in skus if s.lead_time_days is not None]
        summaries.append(SupplierSummary(
            supplier=setting.supplier, holding_months=setting.holding_months, sku_count=len(skus),
            skus_to_order=sum(1 for s in skus if s.status == SkuStatus.TO_ORDER),
            total_order_qty=sum(s.order_qty or 0 for s in skus),
            blocked_skus=sum(1 for s in skus if s.status == SkuStatus.HOLDING_NOT_SET),
            no_demand_skus=sum(1 for s in skus if s.status == SkuStatus.NO_DEMAND_DATA),
            zero_forecast_skus=sum(1 for s in skus if s.zero_forecast),
            max_lead_time_days=max(leads) if leads else None))
    summaries.sort(key=lambda x: (-x.total_order_qty, x.supplier))
    return summaries
