import type { HoldingPlan, MonthPlan, SkuResult, SkuStatus, SupplierSummary } from '../types'

/** Which plan the order figures come from: the order plan (ordering every order cycle) or the order demand forecast. */
export type PlanMode = 'plan' | 'forecast'

export const MODE_LABEL: Record<PlanMode, string> = { plan: 'Order plan', forecast: 'Order demand forecast' }

/** The mode in the URL (`?mode=forecast`); anything else, including no parameter, is the order plan. */
export function readMode(params: URLSearchParams): PlanMode {
  return params.get('mode') === 'forecast' ? 'forecast' : 'plan'
}

/** Every SKU carries an order plan (false for plans saved before the order cycle setting). */
export function hasOrderPlan(plan: HoldingPlan): boolean {
  return plan.skus.every((s) => s.order_plan !== null)
}

export interface SkuView {
  status: SkuStatus
  orderQty: number | null
  moqApplied: boolean
  months: MonthPlan[] | null
  total: number | null // null when holding is not set or there are no months
}

/** A SKU's this-month order, status and 12 months in the chosen mode. */
export function skuView(s: SkuResult, mode: PlanMode): SkuView {
  const months = mode === 'plan' ? s.order_plan : s.monthly
  const total = !months || s.holding_months === null ? null : months.reduce((sum, m) => sum + (m.order ?? 0), 0)
  if (mode === 'forecast') {
    return { status: s.status, orderQty: s.order_qty, moqApplied: s.moq_applied, months, total }
  }
  // An older run has no order plan; pages show "Recalculate" instead, so the status falls back only to keep a value.
  return { status: s.plan_status ?? s.status, orderQty: s.plan_order_qty, moqApplied: s.plan_moq_applied, months, total }
}

/** The count cards' figures in the chosen mode; null for an older run in plan mode. */
export function modeCounts(plan: HoldingPlan, mode: PlanMode): Record<string, number> | null {
  return mode === 'plan' ? plan.plan_counts : plan.counts
}

export interface SummaryView {
  skusToOrder: number | null
  totalOrderQty: number | null
  monthly: (number | null)[] | null
  twelveMonthTotal: number | null
}

/** A principal's this-month purchase order and monthly totals in the chosen mode. */
export function summaryView(s: SupplierSummary, mode: PlanMode): SummaryView {
  return mode === 'plan'
    ? {
        skusToOrder: s.plan_skus_to_order,
        totalOrderQty: s.plan_total_order_qty,
        monthly: s.plan_monthly_order_qty,
        twelveMonthTotal: s.plan_twelve_month_total,
      }
    : {
        skusToOrder: s.skus_to_order,
        totalOrderQty: s.total_order_qty,
        monthly: s.monthly_order_qty,
        twelveMonthTotal: s.twelve_month_total,
      }
}

/** SKUs to order this month in the chosen mode, grouped by principal: the lines for one purchase order. */
export function poLines(skus: SkuResult[], mode: PlanMode): Map<string, SkuResult[]> {
  const map = new Map<string, SkuResult[]>()
  for (const sku of skus) {
    if ((skuView(sku, mode).orderQty ?? 0) <= 0) continue
    const lines = map.get(sku.supplier) ?? []
    lines.push(sku)
    map.set(sku.supplier, lines)
  }
  for (const lines of map.values()) {
    lines.sort((a, b) => a.description.localeCompare(b.description) || a.sap_code.localeCompare(b.sap_code))
  }
  return map
}

/** How a month's order cell reads: no order calculated (holding not set), a month between orders, or an order. */
export function orderCell(m: MonthPlan): 'blocked' | 'not-order-month' | 'order' {
  if (m.order === null) return 'blocked'
  return m.order_month ? 'order' : 'not-order-month'
}
