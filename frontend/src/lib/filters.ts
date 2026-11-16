import { skuView, type PlanMode } from './mode'
import type { City, SkuResult, SkuStatus } from '../types'

export interface SkuFilter {
  supplier: string | null
  status: SkuStatus | null
  zeroForecastOnly: boolean
  search: string
  city?: City | null // one city's rows only; null or missing for every row
}

const STATUS_ORDER: Record<SkuStatus, number> = {
  TO_ORDER: 0,
  HOLDING_NOT_SET: 1,
  NO_DEMAND_DATA: 2,
  NO_ORDER_NEEDED: 3,
}

/**
 * Filtered SKUs sorted by status (to order first), then order qty descending (no order qty last),
 * then supplier and description. Status and order qty are the chosen mode's.
 */
export function filterSkus(skus: SkuResult[], f: SkuFilter, mode: PlanMode = 'forecast'): SkuResult[] {
  const needle = f.search.trim().toLowerCase()
  const view = new Map(skus.map((s) => [s, skuView(s, mode)]))
  const status = (s: SkuResult) => view.get(s)!.status
  const qty = (s: SkuResult) => view.get(s)!.orderQty
  return skus
    .filter((s) => f.supplier === null || s.supplier === f.supplier)
    .filter((s) => !f.city || s.city === f.city)
    .filter((s) => f.status === null || status(s) === f.status)
    .filter((s) => !f.zeroForecastOnly || s.zero_forecast)
    .filter(
      (s) =>
        needle === '' ||
        s.sap_code.toLowerCase().includes(needle) ||
        s.description.toLowerCase().includes(needle),
    )
    .sort((a, b) => {
      if (status(a) !== status(b)) return STATUS_ORDER[status(a)] - STATUS_ORDER[status(b)]
      const qa = qty(a)
      const qb = qty(b)
      if (qa !== qb) {
        if (qa === null) return 1
        if (qb === null) return -1
        return qb - qa
      }
      return a.supplier.localeCompare(b.supplier) || a.description.localeCompare(b.description)
    })
}
