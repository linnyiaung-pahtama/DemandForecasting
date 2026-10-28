import type { SkuResult, SkuStatus } from '../types'

export interface SkuFilter {
  supplier: string | null
  status: SkuStatus | null
  zeroForecastOnly: boolean
  search: string
}

const STATUS_ORDER: Record<SkuStatus, number> = {
  TO_ORDER: 0,
  HOLDING_NOT_SET: 1,
  NO_DEMAND_DATA: 2,
  NO_ORDER_NEEDED: 3,
}

/**
 * Filtered SKUs sorted by status (to order first), then order qty descending (no order qty last),
 * then supplier and description.
 */
export function filterSkus(skus: SkuResult[], f: SkuFilter): SkuResult[] {
  const needle = f.search.trim().toLowerCase()
  return skus
    .filter((s) => f.supplier === null || s.supplier === f.supplier)
    .filter((s) => f.status === null || s.status === f.status)
    .filter((s) => !f.zeroForecastOnly || s.zero_forecast)
    .filter(
      (s) =>
        needle === '' ||
        s.sap_code.toLowerCase().includes(needle) ||
        s.description.toLowerCase().includes(needle),
    )
    .sort((a, b) => {
      if (a.status !== b.status) return STATUS_ORDER[a.status] - STATUS_ORDER[b.status]
      if (a.order_qty !== b.order_qty) {
        if (a.order_qty === null) return 1
        if (b.order_qty === null) return -1
        return b.order_qty - a.order_qty
      }
      return a.supplier.localeCompare(b.supplier) || a.description.localeCompare(b.description)
    })
}
