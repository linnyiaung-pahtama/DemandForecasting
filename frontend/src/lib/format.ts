import type { PlanMode } from './mode'
import type { DemandValue, HoldingPlan, SkuResult, SkuStatus } from '../types'

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
export function orderExplanation(r: SkuResult, planDate: string, mode: PlanMode = 'forecast'): string[] {
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
  // Runs saved before the stock reports have no PG/PDG breakdown: they keep the single sellable figure.
  const available =
    r.pg_sellable !== null && r.pdg_sellable !== null
      ? `Available = ${fmtExact(r.pg_sellable)} PG sellable + ${fmtExact(r.pdg_sellable)} PDG sellable + ${fmtExact(r.sit)} SIT = ${fmtExact(r.available)}`
      : `Available = ${fmtExact(r.sellable)} sellable + ${fmtExact(r.sit)} SIT = ${fmtExact(r.available)}`

  // The order plan tops stock up to the order-up-to level instead of the target; the steps are otherwise the same.
  const plan = mode === 'plan'
  const level = plan ? r.plan_order_up_to : r.target
  const required = plan ? r.plan_required : r.required
  const orderQty = plan ? r.plan_order_qty : r.order_qty
  const moqApplied = plan ? r.plan_moq_applied : r.moq_applied

  if (r.holding_months === null || level === null || required === null) {
    lines.push(holdingNotSet, available)
  } else {
    const levelLine = plan
      ? `Order-up-to = ${fmtExact(r.buffer)} × (${fmtMonths(r.holding_months)} + ${r.order_cycle_months ?? 1} − 1) months = ${fmtExact(level)}`
      : `Target = ${fmtExact(r.buffer)} × ${plural(r.holding_months, 'month')} = ${fmtExact(level)}`
    lines.push(levelLine, available)
    if (required === 0) {
      lines.push(`Required = 0 (available already covers the ${plan ? 'order-up-to level' : 'target'})`)
    } else {
      const gap = level - r.available
      const roundedUp = Math.abs(gap - required) > EPSILON
      lines.push(
        `Required = ${fmtExact(level)} − ${fmtExact(r.available)} = ` +
          (roundedUp ? `${fmtExact(gap)}, rounded up to ${fmtQty(required)}` : fmtQty(required)),
      )
    }
    if (moqApplied && r.moq > 0 && orderQty !== null) {
      lines.push(
        `MOQ check: ${fmtQty(required)} is below the MOQ of ${fmtQty(r.moq)}, so the order is ${fmtQty(orderQty)}`,
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
    lines.push('Next calculation date: lead time not set')
  } else {
    lines.push(`Next calculation date: lead time of ${r.lead_time_days} days is not valid`)
  }
  return lines
}

/** A plan saved before MOQ and lead time moved to supplier settings: its settings record no MOQ. */
export function isLegacyRun(plan: HoldingPlan): boolean {
  return plan.settings_used.some((s) => s.moq === null)
}

/** The plan carries a 12-month plan for every SKU (false for plans saved before it existed). */
export function hasMonthly(plan: HoldingPlan): boolean {
  return plan.plan_months.length > 0 && plan.skus.every((s) => s.monthly !== null)
}

/** The SKU's demand value for each actual month, then each forecast month; null where it has none. */
export function demandColumns(r: SkuResult, actualMonths: string[], forecastMonths: string[]): (DemandValue | null)[] {
  const find = (source: DemandValue['source'], month: string) =>
    r.demand_values.find((d) => d.source === source && d.month === month) ?? null
  return [...actualMonths.map((m) => find('actual', m)), ...forecastMonths.map((m) => find('forecast', m))]
}

/** A SKU's total cartons over the 12 months; null when its holding is not set or it has no 12-month plan. */
export function monthlyTotal(r: SkuResult): number | null {
  if (r.monthly === null || r.holding_months === null) return null
  return r.monthly.reduce((sum, m) => sum + (m.order ?? 0), 0)
}