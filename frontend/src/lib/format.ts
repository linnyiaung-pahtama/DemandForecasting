import type { FlagCode } from '../types'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** Whole numbers with thousands separators; one decimal if under 10 and not whole. */
export function fmtQty(n: number): string {
  const rounded = Math.round(n)
  if (Math.abs(n) < 10 && n !== rounded) {
    return n.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
  }
  return rounded.toLocaleString('en-US')
}

/** "2026-10-12" -> "12 Oct 2026". Accepts a date or date-time ISO string. */
export function fmtDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!match) return iso
  const [, year, month, day] = match
  const monthName = MONTHS[Number(month) - 1]
  if (!monthName) return iso
  return `${Number(day)} ${monthName} ${year}`
}

const FLAG_LABELS: Record<FlagCode, string> = {
  ORDER_NOW: 'Order now',
  STOCKOUT_RISK: 'Stock-out risk',
  EXCESS: 'Excess stock',
  EXPIRY_RISK: 'Expiry risk',
  NO_FORECAST_HOLDING_STOCK: 'No forecast, holding stock',
  MTD_ABOVE_FORECAST: 'MTD above forecast',
  LEAD_TIME_EXCEEDS_REORDER: 'Lead time ≥ reorder level',
  MOQ_EXCEEDS_SHELF_LIFE: 'MOQ exceeds shelf life',
  MISSING_LEAD_TIME: 'Missing lead time',
}

export function flagLabel(code: FlagCode): string {
  return FLAG_LABELS[code]
}
