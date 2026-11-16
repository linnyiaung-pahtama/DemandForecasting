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

/** 'YGN' -> "Yangon", 'MDY' -> "Mandalay"; "—" for the combined rows of runs saved before the city split. */
export function cityLabel(city: string | null): string {
  return city === 'YGN' ? 'Yangon' : city === 'MDY' ? 'Mandalay' : '—'
}

/** "2026-10-17" -> "17 Oct" (no year). */
export function fmtDayMonth(iso: string): string {
  return fmtDate(iso).replace(/ \d{4}$/, '')
}

/** The run-out flag as a sentence, e.g. "Runs out about 17 Oct, before its stock in transit arrives on 19 Oct". */
export function runOutMessage(s: SkuResult): string | null {
  if (!s.runs_out_on || !s.runs_out_arrival) return null
  return `Runs out about ${fmtDayMonth(s.runs_out_on)}, before its stock in transit arrives on ${fmtDayMonth(s.runs_out_arrival)}`
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

/** A month count as stored: decimals allowed (1.5, 12.5), so never rounded to a whole number. */
export function fmtMonths(n: number): string {
  return String(n)
}

/** Days in a month for the holding: buffer = average monthly sales ÷ 30 × holding days. */
export const DAYS_PER_MONTH = 30

/** A principal's holding, e.g. "60 days"; `blank` when it is not set. */
export function fmtHolding(days: number | null, blank = '—'): string {
  return days === null ? blank : `${fmtQty(days)} day${days === 1 ? '' : 's'}`
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

/** How often a principal is ordered from, e.g. "every 4 weeks"; "—" for a run saved before the weekly cycle. */
export function fmtCycle(weeks: number | null): string {
  if (weeks === null) return '—'
  return weeks === 1 ? 'every week' : `every ${weeks} weeks`
}

/** The order cycle for a narrow table column, e.g. "4 wk". */
export function fmtCycleShort(weeks: number | null): string {
  return weeks === null ? '—' : `${weeks} wk`
}

/**
 * One line per calculation step, built only from the numbers stored on the SKU result so the
 * planner can follow the arithmetic. `planDate` is the plan's date (ISO), used for the last line.
 */
export function orderExplanation(r: SkuResult, planDate: string, mode: PlanMode = 'forecast'): string[] {
  // A plan saved before the order cycle has no order plan to explain; its holding may well be set.
  if (mode === 'plan' && r.order_plan === null) return ['Recalculate to see the order plan.']
  const monthCount = r.demand_values.length
  const holdingNotSet = `Holding not set for ${r.supplier} — no order calculated`
  const valid = r.demand_values.filter((d) => d.valid && d.value !== null).map((d) => d.value as number)

  if (r.avg_sales === null || valid.length === 0) {
    const lines = [`No valid demand values (all ${monthCount} months are zero, negative or missing)`]
    if (r.holding_days === null) lines.push(holdingNotSet)
    return lines
  }

  const avg = r.avg_sales
  const lines = [`Avg sales = (${valid.map(fmtExact).join(' + ')}) ÷ ${r.valid_count} = ${fmtExact(avg)} a month`]
  if (r.buffer !== null && r.holding_days !== null) {
    lines.push(
      `Buffer = ${fmtExact(avg)} ÷ ${DAYS_PER_MONTH} × ${plural(r.holding_days, 'day')} = ${fmtExact(r.buffer)}`,
    )
  }
  // Runs saved before the stock reports have no PG/PDG breakdown: they keep the single sellable figure.
  const available =
    r.pg_sellable !== null && r.pdg_sellable !== null
      ? `Available = ${fmtExact(r.pg_sellable)} PG sellable + ${fmtExact(r.pdg_sellable)} PDG sellable + ${fmtExact(r.sit)} SIT = ${fmtExact(r.available)}`
      : `Available = ${fmtExact(r.sellable)} sellable + ${fmtExact(r.sit)} SIT = ${fmtExact(r.available)}`

  // The order demand forecast tops stock up to the buffer (its target); the order plan tops it up to the
  // order-up-to level. The steps are otherwise the same.
  const plan = mode === 'plan'
  const level = plan ? r.plan_order_up_to : r.target
  const required = plan ? r.plan_required : r.required
  const orderQty = plan ? r.plan_order_qty : r.order_qty
  const moqApplied = plan ? r.plan_moq_applied : r.moq_applied

  if (r.holding_days === null || r.buffer === null || level === null || required === null) {
    lines.push(holdingNotSet, available)
  } else {
    if (plan) {
      // The weekly order-up-to is never below one cycle's sales, which only bites for a holding under 30 days.
      const weeks = r.order_cycle_weeks ?? 0
      lines.push(
        r.holding_days < DAYS_PER_MONTH
          ? `Order-up-to = ${fmtExact(avg)} × ${weeks} × 12 ÷ 52 = ${fmtExact(level)} (one cycle's sales; the holding is under ${DAYS_PER_MONTH} days)`
          : `Order-up-to = ${fmtExact(r.buffer)} + ${fmtExact(avg)} × (${weeks} × 12 ÷ 52 − 1) = ${fmtExact(level)}`,
      )
    }
    lines.push(available)
    if (required === 0) {
      lines.push(`Required = 0 (available already covers the ${plan ? 'order-up-to level' : 'buffer'})`)
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
    if (plan) lines.push(`This is the order on ${fmtDate(planDate)}; the next orders are listed under Orders.`)
  }

  if (r.stock_cover_months !== null) {
    lines.push(`Stock cover = ${fmtExact(r.available)} ÷ ${fmtExact(avg)} = ${fmtCover(r.stock_cover_months)} months`)
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
  if (r.monthly === null || r.holding_days === null) return null
  return r.monthly.reduce((sum, m) => sum + (m.order ?? 0), 0)
}