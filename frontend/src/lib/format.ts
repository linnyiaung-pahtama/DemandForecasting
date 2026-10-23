import type { FlagCode, PlannedOrder } from '../types'

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

export const FLAG_LABELS: Record<FlagCode, string> = {
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

/** The "why" for one order, built only from numbers the engine recorded. */
export function orderReason(o: PlannedOrder): string {
  const r = o.reason
  let text =
    `On ${fmtDate(o.order_date)} stock + on order = ${fmtQty(r.inventory_position)}, ` +
    `below reorder level ${fmtQty(r.reorder_qty)}. ` +
    `Ordering ${fmtQty(o.qty)} to reach target ${fmtQty(r.target_qty)}.`
  if (r.moq_applied) text += ' (raised to MOQ)'
  if (r.cap_applied) text += ` (capped by shelf life at ${fmtQty(r.shelf_life_cap ?? 0)})`
  text += ` Expected stock when it arrives: ${fmtQty(r.stock_at_arrival)}.`
  return text
}

const SEVERE: FlagCode[] = ['ORDER_NOW', 'STOCKOUT_RISK']
const WARN: FlagCode[] = [
  'EXCESS',
  'EXPIRY_RISK',
  'LEAD_TIME_EXCEEDS_REORDER',
  'MOQ_EXCEEDS_SHELF_LIFE',
  'MISSING_LEAD_TIME',
]

/** CSS class for a flag chip: red for urgent, amber for warnings, grey otherwise. */
export function flagTone(code: FlagCode): string {
  if (SEVERE.includes(code)) return 'chip-red'
  if (WARN.includes(code)) return 'chip-amber'
  return 'chip-grey'
}
