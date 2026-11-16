import { fmtDate } from './format'
import type { HoldingPlan, MonthPlan, OrderLine, SitArrival, SkuResult, SkuStatus, SupplierSummary } from '../types'

/** Which plan the order figures come from: the order plan (ordering every order cycle) or the order demand forecast. */
export type PlanMode = 'plan' | 'forecast'

export const MODE_LABEL: Record<PlanMode, string> = { plan: 'Order plan', forecast: 'Order demand forecast' }

/** The stock level each mode's orders top up to; the same figure for a principal ordering every month. */
export const LEVEL_LABEL: Record<PlanMode, string> = { plan: 'Order-up-to', forecast: 'Target' }

/** The mode in the URL (`?mode=forecast`); anything else, including no parameter, is the order plan. */
export function readMode(params: URLSearchParams): PlanMode {
  return params.get('mode') === 'forecast' ? 'forecast' : 'plan'
}

/** The query string that keeps the mode when linking to another page ("" for the default, the order plan). */
export function modeQuery(mode: PlanMode): string {
  return mode === 'forecast' ? '?mode=forecast' : ''
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
  level: number | null // the stock level the orders top up to (LEVEL_LABEL); null when holding is not set
}

/** A SKU's this-month order, status, 12 months and top-up level in the chosen mode. */
export function skuView(s: SkuResult, mode: PlanMode): SkuView {
  const months = mode === 'plan' ? s.order_plan : s.monthly
  const total = !months || s.holding_days === null ? null : months.reduce((sum, m) => sum + (m.order ?? 0), 0)
  if (mode === 'forecast') {
    return { status: s.status, orderQty: s.order_qty, moqApplied: s.moq_applied, months, total, level: s.target }
  }
  // An older run has no order plan; pages show "Recalculate" instead, so the status falls back only to keep a value.
  return {
    status: s.plan_status ?? s.status,
    orderQty: s.plan_order_qty,
    moqApplied: s.plan_moq_applied,
    months,
    total,
    level: s.plan_order_up_to,
  }
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
    lines.sort(
      (a, b) =>
        a.description.localeCompare(b.description) ||
        a.sap_code.localeCompare(b.sap_code) ||
        CITY_ORDER[a.city ?? ''] - CITY_ORDER[b.city ?? ''],
    )
  }
  return map
}

const CITY_ORDER: Record<string, number> = { '': 0, YGN: 1, MDY: 2 }

/** A plan row's key: its SAP code and city (a SKU has a row per city; older runs one row with no city). */
export function rowKey(s: SkuResult): string {
  return `${s.sap_code}|${s.city ?? ''}`
}

/** How a month's order cell reads: no order calculated (holding not set), a month without an order, or an order. */
export function orderCell(m: MonthPlan): 'blocked' | 'not-order-month' | 'order' {
  if (m.order === null) return 'blocked'
  return m.order_month ? 'order' : 'not-order-month'
}

/** The order plan's orders above 0 dated in a month: the month cell lists each with its date. */
export function placedOrders(m: MonthPlan): OrderLine[] {
  return m.orders.filter((o) => o.qty > 0)
}

const DAY_MS = 24 * 60 * 60 * 1000

// ISO dates are handled as UTC midnights so time zones and daylight saving never shift a day.
function toUtc(date: string): number {
  return Date.UTC(Number(date.slice(0, 4)), Number(date.slice(5, 7)) - 1, Number(date.slice(8, 10)))
}

function toIso(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10)
}

/** The Monday (ISO date) of the Monday-to-Sunday week a date falls in. */
export function weekStart(date: string): string {
  const ms = toUtc(date)
  const sinceMonday = (new Date(ms).getUTCDay() + 6) % 7
  return toIso(ms - sinceMonday * DAY_MS)
}

/** The Monday of the week `n` weeks after the one starting on `monday`. */
export function addWeeks(monday: string, n: number): string {
  return toIso(toUtc(monday) + n * 7 * DAY_MS)
}

/**
 * The week columns of the plan: each Monday-to-Sunday week sits under the month its Monday falls in. The first
 * plan month also starts with the week holding its 1st, so an order early in that month has a column.
 */
export function planWeeks(months: string[]): { month: string; weeks: string[] }[] {
  return months.map((month, i) => {
    let monday = weekStart(`${month}-01`)
    if (i > 0 && monday < `${month}-01`) monday = addWeeks(monday, 1)
    const weeks: string[] = []
    for (; monday.slice(0, 7) <= month; monday = addWeeks(monday, 1)) weeks.push(monday)
    return { month, weeks }
  })
}

/** Every order of the plan, 0-quantity ones included, keyed by the Monday of the week it is placed in. */
export function ordersByWeek(months: MonthPlan[]): Map<string, OrderLine[]> {
  const byWeek = new Map<string, OrderLine[]>()
  for (const o of months.flatMap((m) => m.orders)) {
    const key = weekStart(o.date)
    byWeek.set(key, [...(byWeek.get(key) ?? []), o])
  }
  return byWeek
}

/**
 * A SKU's SIT by the day it lands, sorted, as the order plan uses it: an arrival dated before the plan date lands on
 * the plan date (added to any arrival already there). A run saved before the Stock in Transit file has no arrivals,
 * so all its SIT lands on the plan date.
 */
export function skuArrivals(s: SkuResult, planDate: string): SitArrival[] {
  if (s.sit_arrivals == null) return s.sit !== 0 ? [{ date: planDate, cartons: s.sit, source: 'sit' }] : []
  // One entry per day and source, so a commit stays apart from a file delivery on the same day.
  const byDay = new Map<string, SitArrival>()
  for (const a of s.sit_arrivals) {
    const date = a.date < planDate ? planDate : a.date
    const source = a.source ?? 'sit'
    const key = `${date}|${source}`
    const prev = byDay.get(key)
    byDay.set(key, { date, cartons: (prev?.cartons ?? 0) + a.cartons, source })
  }
  return [...byDay.values()].sort(
    (a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0) || (a.source === 'sit' ? -1 : 1),
  )
}

const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "Oct W3" for a week's Monday: W1 is the Monday-to-Sunday week holding the 1st (as in the Stock in Transit file).
 * A sixth week (a month starting on a Sunday) holds the next month's 1st, so it reads as that month's W1. */
function weekLabel(monday: string): string {
  const month = Number(monday.slice(5, 7))
  const firstWeek = weekStart(`${monday.slice(0, 7)}-01`)
  const n = Math.round((toUtc(monday) - toUtc(firstWeek)) / (7 * DAY_MS)) + 1
  return n === 6 ? `${MONTH_ABBR[month % 12]} W1` : `${MONTH_ABBR[month - 1]} W${n}`
}

/** The weeks a commit can arrive in: from the plan date's week to the end of the last plan month, each with its
 * Monday and a label like "Oct W4 (19 Oct)". */
export function commitWeeks(planDate: string, months: string[]): { monday: string; label: string }[] {
  const out: { monday: string; label: string }[] = []
  const last = months[months.length - 1]
  if (!last) return out
  for (let monday = weekStart(planDate); monday.slice(0, 7) <= last; monday = addWeeks(monday, 1)) {
    out.push({ monday, label: `${weekLabel(monday)} (${orderDateLabel({ date: monday, qty: 0, moq_applied: false })})` })
  }
  return out
}

/** The cartons a plan row has from commits entered on New plan (not the Stock in Transit file's deliveries). */
export function commitCartons(s: SkuResult): number {
  return (s.sit_arrivals ?? []).reduce((sum, a) => sum + (a.source === 'commit' ? a.cartons : 0), 0)
}

/** Cartons arriving in a week: from the Stock in Transit file, and from commits entered on New plan. */
export interface WeekArrivals {
  sit: number
  commit: number
}

/** Cartons arriving in each Monday-to-Sunday week, keyed by its Monday, with the file's SIT and commits apart. */
export function arrivalsByWeek(arrivals: SitArrival[]): Map<string, WeekArrivals> {
  const byWeek = new Map<string, WeekArrivals>()
  for (const a of arrivals) {
    const key = weekStart(a.date)
    const week = byWeek.get(key) ?? { sit: 0, commit: 0 }
    if (a.source === 'commit') week.commit += a.cartons
    else week.sit += a.cartons
    byWeek.set(key, week)
  }
  return byWeek
}

/** An order's day for the month cell, e.g. "7 Dec". */
export function orderDateLabel(o: OrderLine): string {
  return fmtDate(o.date).replace(/ \d{4}$/, '')
}
