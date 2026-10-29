import { describe, expect, it } from 'vitest'
import {
  hasOrderPlan,
  MODE_LABEL,
  modeCounts,
  modeQuery,
  orderCell,
  poLines,
  readMode,
  skuView,
  summaryView,
} from './mode'
import type { HoldingPlan, MonthPlan, SkuResult, SupplierSummary } from '../types'

const month = (key: string, order: number | null, order_month = true, moq_applied = false): MonthPlan => ({
  month: key,
  opening: 0,
  demand: 0,
  order,
  moq_applied,
  closing: 0,
  order_month,
})

// A cycle-3 SKU: the forecast orders 100 this month, the order plan 340 (then nothing until month 4).
const forecastMonths = [month('2026-10', 100), month('2026-11', 120), month('2026-12', 120), month('2027-01', 120)]
const planMonths = [
  month('2026-10', 340),
  month('2026-11', 0, false),
  month('2026-12', 0, false),
  month('2027-01', 360),
]

function sku(code: string, supplier: string, extra: Partial<SkuResult> = {}): SkuResult {
  return {
    sap_code: code,
    supplier,
    description: `item ${code}`,
    holding_months: 3,
    status: 'TO_ORDER',
    order_qty: 100,
    moq_applied: false,
    monthly: forecastMonths,
    order_cycle_months: 3,
    order_plan: planMonths,
    plan_order_qty: 340,
    plan_moq_applied: true,
    plan_status: 'TO_ORDER',
    zero_forecast: false,
    ...extra,
  } as SkuResult
}

describe('readMode', () => {
  it('is the order plan unless the URL asks for the forecast', () => {
    expect(readMode(new URLSearchParams(''))).toBe('plan')
    expect(readMode(new URLSearchParams('mode=plan'))).toBe('plan')
    expect(readMode(new URLSearchParams('mode=other'))).toBe('plan')
    expect(readMode(new URLSearchParams('mode=forecast'))).toBe('forecast')
  })

  it('builds the query string that keeps the mode in a link', () => {
    expect(modeQuery('plan')).toBe('')
    expect(modeQuery('forecast')).toBe('?mode=forecast')
    expect(readMode(new URLSearchParams(modeQuery('forecast')))).toBe('forecast')
  })

  it('labels both modes', () => {
    expect(MODE_LABEL).toEqual({ plan: 'Order plan', forecast: 'Order demand forecast' })
  })
})

describe('skuView', () => {
  it('picks the forecast or the order plan values', () => {
    const s = sku('1', 'A')
    expect(skuView(s, 'forecast')).toEqual({
      status: 'TO_ORDER',
      orderQty: 100,
      moqApplied: false,
      months: forecastMonths,
      total: 460,
    })
    expect(skuView(s, 'plan')).toEqual({ status: 'TO_ORDER', orderQty: 340, moqApplied: true, months: planMonths, total: 700 })
  })

  it('has no total when holding is not set or there are no months', () => {
    const blocked = sku('1', 'A', { holding_months: null, order_plan: [month('2026-10', null)] })
    expect(skuView(blocked, 'plan').total).toBeNull()
    expect(skuView(sku('1', 'A', { order_plan: null }), 'plan').total).toBeNull()
  })
})

describe('hasOrderPlan', () => {
  const plan = (skus: SkuResult[]) => ({ skus }) as HoldingPlan
  it('is true only when every SKU carries an order plan', () => {
    expect(hasOrderPlan(plan([sku('1', 'A'), sku('2', 'B')]))).toBe(true)
    expect(hasOrderPlan(plan([sku('1', 'A'), sku('2', 'B', { order_plan: null })]))).toBe(false)
  })
})

describe('modeCounts', () => {
  const counts = { TO_ORDER: 1, NO_ORDER_NEEDED: 2 }
  it('returns the mode counts, or null for an older run in plan mode', () => {
    const p = { counts, plan_counts: { TO_ORDER: 3, NO_ORDER_NEEDED: 0 } } as unknown as HoldingPlan
    expect(modeCounts(p, 'forecast')).toBe(counts)
    expect(modeCounts(p, 'plan')).toEqual({ TO_ORDER: 3, NO_ORDER_NEEDED: 0 })
    expect(modeCounts({ counts, plan_counts: null } as unknown as HoldingPlan, 'plan')).toBeNull()
  })
})

describe('summaryView', () => {
  const s = {
    skus_to_order: 1,
    total_order_qty: 100,
    monthly_order_qty: [100, 120],
    twelve_month_total: 220,
    plan_skus_to_order: 2,
    plan_total_order_qty: 340,
    plan_monthly_order_qty: [340, null],
    plan_twelve_month_total: 340,
  } as SupplierSummary
  it('picks the mode figures', () => {
    expect(summaryView(s, 'forecast')).toEqual({ skusToOrder: 1, totalOrderQty: 100, monthly: [100, 120], twelveMonthTotal: 220 })
    expect(summaryView(s, 'plan')).toEqual({ skusToOrder: 2, totalOrderQty: 340, monthly: [340, null], twelveMonthTotal: 340 })
  })
})

describe('poLines', () => {
  // '2' needs no order in the forecast but does in the order plan; '3' is ordered in neither
  const skus = [
    sku('1', 'A', { description: 'b' }),
    sku('2', 'A', { description: 'a', status: 'NO_ORDER_NEEDED', order_qty: 0, plan_order_qty: 200 }),
    sku('3', 'B', { order_qty: 0, plan_order_qty: 0 }),
    sku('4', 'C', { holding_months: null, order_qty: null, plan_order_qty: null }),
  ]
  it('groups the SKUs to order by principal, in the chosen mode', () => {
    const forecast = poLines(skus, 'forecast')
    expect([...forecast.keys()]).toEqual(['A'])
    expect(forecast.get('A')!.map((s) => s.sap_code)).toEqual(['1'])
    const plan = poLines(skus, 'plan')
    expect(plan.get('A')!.map((s) => s.sap_code)).toEqual(['2', '1'])   // sorted by description
    expect(plan.has('B') || plan.has('C')).toBe(false)
  })
})

describe('orderCell', () => {
  it('tells blocked, between-order and order months apart', () => {
    expect(orderCell(month('2026-10', null))).toBe('blocked')
    expect(orderCell(month('2026-11', null, false))).toBe('blocked')
    expect(orderCell(month('2026-11', 0, false))).toBe('not-order-month')
    expect(orderCell(month('2026-10', 0))).toBe('order')
    expect(orderCell(month('2026-10', 340))).toBe('order')
  })
})
