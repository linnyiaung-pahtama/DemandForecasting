import type { FlagCode, PlannedOrder, SkuPlan } from '../types'

export interface SkuFilter {
  supplier: string | null
  flag: FlagCode | null
  dueWithinWeeks: number | null
  search: string
}

/** ISO date (YYYY-MM-DD) plus whole days, using UTC arithmetic so no timezone can shift it. */
export function addDaysIso(iso: string, days: number): string {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10)
}

/** The earliest order of a SKU, or null if it has none. */
export function nextOrder(sku: SkuPlan): PlannedOrder | null {
  let best: PlannedOrder | null = null
  for (const o of sku.orders) {
    if (best === null || o.order_date < best.order_date) best = o
  }
  return best
}

/** Orders with order date earlier than planDate + 7 * weeks days (exclusive). */
export function ordersInWindow(sku: SkuPlan, planDate: string, weeks: number): PlannedOrder[] {
  const limit = addDaysIso(planDate, 7 * weeks)
  return sku.orders.filter((o) => o.order_date.slice(0, 10) < limit)
}

/** Filtered SKUs sorted by next order date (SKUs without orders last), supplier, description. */
export function filterSkus(skus: SkuPlan[], f: SkuFilter, planDate: string): SkuPlan[] {
  const needle = f.search.trim().toLowerCase()
  const rows = skus
    .filter((s) => f.supplier === null || s.supplier === f.supplier)
    .filter((s) => f.flag === null || s.flags.some((fl) => fl.code === f.flag))
    .filter((s) => f.dueWithinWeeks === null || ordersInWindow(s, planDate, f.dueWithinWeeks).length > 0)
    .filter(
      (s) =>
        needle === '' ||
        s.sap_code.toLowerCase().includes(needle) ||
        s.description.toLowerCase().includes(needle),
    )
    .map((s) => ({ s, next: nextOrder(s)?.order_date ?? null }))
  rows.sort((a, b) => {
    if (a.next !== b.next) {
      if (a.next === null) return 1
      if (b.next === null) return -1
      return a.next < b.next ? -1 : 1
    }
    return (
      a.s.supplier.localeCompare(b.s.supplier) || a.s.description.localeCompare(b.s.description)
    )
  })
  return rows.map((r) => r.s)
}
