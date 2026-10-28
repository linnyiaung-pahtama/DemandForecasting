import type { SkuResult, SkuStatus } from '../types'

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

/** "2026-10-12T09:05:33" -> "09:05". An ISO string without a time part is returned as "". */
export function fmtTime(iso: string): string {
  const match = /[T ](\d{2}:\d{2})/.exec(iso)
  return match ? match[1] : ''
}

/** "2026-07" -> "Jul 2026". An unrecognised key is returned unchanged. */
export function monthLabel(key: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(key)
  if (!match) return key
  const monthName = MONTHS[Number(match[2]) - 1]
  return monthName ? `${monthName} ${match[1]}` : key
}

export function statusLabel(s: SkuStatus): string {
  switch (s) {
    case 'TO_ORDER':
      return 'To order'
    case 'NO_ORDER_NEEDED':
      return 'No order needed'
    case 'HOLDING_NOT_SET':
      return 'Holding not set'
    case 'NO_DEMAND_DATA':
      return 'No demand data'
  }
}

/** Holding in months as stored: decimals allowed (1.5, 12.5), so never rounded to a whole number. */
export function fmtMonths(n: number): string {
  return String(n)
}

/** Stock cover in months, one decimal ("2.2"); "—" when it cannot be calculated. */
export function fmtCover(n: number | null): string {
  return n === null ? '—' : n.toFixed(1)
}

/** An exact figure for the arithmetic lines: up to 4 decimals, trailing zeros trimmed, thousands separators. */
export function fmtExact(n: number): string {
  return n.toLocaleString('en-US', { maximumFractionDigits: 4 })
}

const EPSILON = 1e-9

function plural(n: number, unit: string): string {
  return `${n} ${unit}${n === 1 ? '' : 's'}`
}

/**
 * One line per calculation step, built only from the numbers stored on the SKU result so the
 * planner can follow the arithmetic. `planDate` is the plan's date (ISO), used for the last line.
 */
export function orderExplanation(r: SkuResult, planDate: string): string[] {
  const monthCount = r.demand_values.length
  const holdingNotSet = `Holding not set for ${r.supplier} — no order calculated`
  const valid = r.demand_values.filter((d) => d.valid && d.value !== null).map((d) => d.value as number)

  if (r.buffer === null || valid.length === 0) {
    const lines = [`No valid demand values (all ${monthCount} months are zero, negative or missing)`]
    if (r.holding_months === null) lines.push(holdingNotSet)
    return lines
  }

  const lines = [
    `Buffer = (${valid.map(fmtExact).join(' + ')}) ÷ ${r.valid_count} = ${fmtExact(r.buffer)} a month`,
  ]
  const available = `Available = ${fmtExact(r.sellable)} sellable + ${fmtExact(r.sit)} SIT = ${fmtExact(r.available)}`

  if (r.holding_months === null || r.target === null || r.required === null) {
    lines.push(holdingNotSet, available)
  } else {
    lines.push(`Target = ${fmtExact(r.buffer)} × ${plural(r.holding_months, 'month')} = ${fmtExact(r.target)}`, available)
    if (r.required === 0) {
      lines.push('Required = 0 (available already covers the target)')
    } else {
      const gap = r.target - r.available
      const roundedUp = Math.abs(gap - r.required) > EPSILON
      lines.push(
        `Required = ${fmtExact(r.target)} − ${fmtExact(r.available)} = ` +
          (roundedUp ? `${fmtExact(gap)}, rounded up to ${fmtQty(r.required)}` : fmtQty(r.required)),
      )
    }
    if (r.moq_applied && r.moq > 0 && r.order_qty !== null) {
      lines.push(
        `MOQ check: ${fmtQty(r.required)} is below the MOQ of ${fmtQty(r.moq)}, so the order is ${fmtQty(r.order_qty)}`,
      )
    }
  }

  if (r.stock_cover_months !== null) {
    lines.push(`Stock cover = ${fmtExact(r.available)} ÷ ${fmtExact(r.buffer)} = ${fmtCover(r.stock_cover_months)} months`)
  }

  if (r.next_calc_date !== null && r.lead_time_days !== null) {
    lines.push(
      `Next calculation date = ${fmtDate(planDate)} + ${plural(r.lead_time_days, 'day')} lead time = ${fmtDate(r.next_calc_date)}`,
    )
  } else if (r.lead_time_days === null) {
    lines.push('Next calculation date: no lead time')
  } else {
    lines.push(`Next calculation date: lead time of ${r.lead_time_days} days is not valid`)
  }
  return lines
}
