import { describe, expect, it } from 'vitest'
import {
  hasOrderPlan,
  LEVEL_LABEL,
  MODE_LABEL,
  modeCounts,
  modeQuery,
  orderCell,
  commitCartons,
  commitWeeks,
  orderDateLabel,
  ordersByWeek,
  arrivalsByWeek,
  skuArrivals,
  placedOrders,
  planWeeks,
  weekStart,
  poLines,
  readMode,
  rowKey,
  skuView,
  summaryView,
} from './mode'
import type { HoldingPlan, MonthPlan, OrderLine, SkuResult, SupplierSummary } from '../types'

const month = (
  key: string,
  order: number | null,
  order_month = true,
  moq_applied = false,
  orders: OrderLine[] = [],
): MonthPlan => ({
  month: key,
  opening: 0,
  demand: 0,
  order,
  moq_applied,
  closing: 0,
  order_month,
  orders,
  arrivals: null,
})

// A long-cycle SKU: the forecast orders 100 this month, the order plan 340 (then nothing until month 4).
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
    holding_days: 90,
    status: 'TO_ORDER',
    order_qty: 100,
    moq_applied: false,
    monthly: forecastMonths,
    order_cycle_weeks: 13,
    order_plan: planMonths,
    plan_order_qty: 340,
    plan_moq_applied: true,
    plan_status: 'TO_ORDER',
    target: 360,
    plan_order_up_to: 600,
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

  it('labels the stock level each mode tops up to', () => {
    expect(LEVEL_LABEL).toEqual({ plan: 'Order-up-to', forecast: 'Target' })
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
      level: 360,
    })
    expect(skuView(s, 'plan')).toEqual({
      status: 'TO_ORDER',
      orderQty: 340,
      moqApplied: true,
      months: planMonths,
      total: 700,
      level: 600,
    })
  })

  it('has no total when holding is not set or there are no months', () => {
    const blocked = sku('1', 'A', { holding_days: null, order_plan: [month('2026-10', null)] })
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
    sku('4', 'C', { holding_days: null, order_qty: null, plan_order_qty: null }),
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

describe('placedOrders', () => {
  const jan = month('2027-01', 217, true, false, [
    { date: '2027-01-02', qty: 108, moq_applied: false },
    { date: '2027-01-30', qty: 109, moq_applied: false },
  ])

  it('lists the orders above 0 placed in a month', () => {
    expect(placedOrders(jan).map((o) => o.qty)).toEqual([108, 109])
    const withZero = month('2026-10', 91, true, false, [
      { date: '2026-10-10', qty: 0, moq_applied: false },
      { date: '2026-10-31', qty: 91, moq_applied: false },
    ])
    expect(placedOrders(withZero).map((o) => o.date)).toEqual(['2026-10-31'])
    expect(placedOrders(month('2026-11', 0, false))).toEqual([])
  })

})

describe('Monday-to-Sunday weeks', () => {
  it('finds the Monday a date belongs to', () => {
    expect(weekStart('2026-10-12')).toBe('2026-10-12') // a Monday
    expect(weekStart('2026-10-14')).toBe('2026-10-12') // Wednesday
    expect(weekStart('2026-11-01')).toBe('2026-10-26') // Sunday belongs to the week before
    expect(weekStart('2027-01-01')).toBe('2026-12-28') // across the year end
  })

  it('puts each week under the month its Monday falls in', () => {
    const weeks = planWeeks(['2026-10', '2026-11', '2026-12', '2027-01', '2027-02', '2027-03'])
    expect(weeks.filter((w) => w.month !== '2026-10' && w.month !== '2027-01').map((w) => [w.month, w.weeks])).toEqual([
      ['2026-11', ['2026-11-02', '2026-11-09', '2026-11-16', '2026-11-23', '2026-11-30']],
      ['2026-12', ['2026-12-07', '2026-12-14', '2026-12-21', '2026-12-28']],
      ['2027-02', ['2027-02-01', '2027-02-08', '2027-02-15', '2027-02-22']],
      ['2027-03', ['2027-03-01', '2027-03-08', '2027-03-15', '2027-03-22', '2027-03-29']],
    ])
  })

  it('starts the first plan month with the week holding its 1st, so early-month orders have a column', () => {
    // 1 Oct 2026 is a Thursday: its week starts on Monday 28 Sep
    expect(planWeeks(['2026-10', '2026-11'])[0].weeks).toEqual([
      '2026-09-28',
      '2026-10-05',
      '2026-10-12',
      '2026-10-19',
      '2026-10-26',
    ])
  })

  it('groups the orders of every month by the week they are placed in, across month ends', () => {
    const months = [
      month('2026-11', 2213, true, false, [{ date: '2026-11-09', qty: 2213, moq_applied: false }]),
      month('2026-12', 2250, true, false, [
        { date: '2026-12-02', qty: 0, moq_applied: false }, // Wednesday of the week starting 30 Nov
        { date: '2026-12-07', qty: 2250, moq_applied: false },
      ]),
    ]
    const byWeek = ordersByWeek(months)
    expect(byWeek.get('2026-11-09')?.map((o) => o.qty)).toEqual([2213])
    expect(byWeek.get('2026-11-30')?.map((o) => o.qty)).toEqual([0])
    expect(byWeek.get('2026-12-07')?.map((o) => o.qty)).toEqual([2250])
    expect(byWeek.has('2026-11-16')).toBe(false)
  })

  it('labels an order with its date', () => {
    expect(orderDateLabel({ date: '2026-12-07', qty: 2250, moq_applied: false })).toBe('7 Dec')
    expect(orderDateLabel({ date: '2027-03-29', qty: 2193, moq_applied: false })).toBe('29 Mar')
  })
})

describe('skuArrivals', () => {
  it('keeps the stored arrivals, sorted', () => {
    const s = sku('A', 'P', {
      sit: 12,
      sit_arrivals: [
        { date: '2026-10-19', cartons: 7 },
        { date: '2026-10-12', cartons: 5 },
      ],
    })
    expect(skuArrivals(s, '2026-10-12')).toEqual([
      { date: '2026-10-12', cartons: 5, source: 'sit' },
      { date: '2026-10-19', cartons: 7, source: 'sit' },
    ])
  })

  it('moves an arrival before the plan date to the plan date and adds it to one already there', () => {
    const s = sku('A', 'P', {
      sit: 9,
      sit_arrivals: [
        { date: '2026-10-12', cartons: 4 },
        { date: '2026-10-14', cartons: 5 },
      ],
    })
    expect(skuArrivals(s, '2026-10-14')).toEqual([{ date: '2026-10-14', cartons: 9, source: 'sit' }])
  })

  it('treats an older run (no arrivals) as all SIT landing on the plan date', () => {
    expect(skuArrivals(sku('A', 'P', { sit: 300, sit_arrivals: null }), '2026-10-12')).toEqual([
      { date: '2026-10-12', cartons: 300, source: 'sit' },
    ])
    expect(skuArrivals(sku('A', 'P', { sit: 0, sit_arrivals: null }), '2026-10-12')).toEqual([])
  })
})

describe('arrivalsByWeek', () => {
  it('adds up the arrivals of each Monday-to-Sunday week, keyed by its Monday', () => {
    const byWeek = arrivalsByWeek([
      { date: '2026-10-12', cartons: 5 },
      { date: '2026-10-14', cartons: 2 },
      { date: '2026-10-26', cartons: 7 },
    ])
    expect([...byWeek]).toEqual([
      ['2026-10-12', { sit: 7, commit: 0 }],
      ['2026-10-26', { sit: 7, commit: 0 }],
    ])
  })
})
describe('rowKey', () => {
  it('tells apart the city rows of one SKU', () => {
    expect(rowKey(sku('A', 'P', { city: 'YGN' }))).toBe('A|YGN')
    expect(rowKey(sku('A', 'P', { city: 'MDY' }))).toBe('A|MDY')
    expect(rowKey(sku('A', 'P', { city: null }))).toBe('A|')
  })
})

describe('poLines by city', () => {
  it('lists Yangon before Mandalay for the same SKU', () => {
    const lines = poLines([sku('A', 'P', { city: 'MDY' }), sku('A', 'P', { city: 'YGN' })], 'forecast').get('P')!
    expect(lines.map((s) => s.city)).toEqual(['YGN', 'MDY'])
  })
})
describe('commits among the arrivals', () => {
  it('keeps a commit apart from stock in transit on the same day, and the week keeps them apart', () => {
    const s = sku('A', 'P', {
      sit: 15,
      sit_arrivals: [
        { date: '2026-10-19', cartons: 5, source: 'sit' },
        { date: '2026-10-19', cartons: 10, source: 'commit' },
      ],
    })
    const list = skuArrivals(s, '2026-10-12')
    expect(list).toEqual([
      { date: '2026-10-19', cartons: 5, source: 'sit' },
      { date: '2026-10-19', cartons: 10, source: 'commit' },
    ])
    // the week keeps the file's stock in transit and the commits apart
    expect([...arrivalsByWeek(list)]).toEqual([['2026-10-19', { sit: 5, commit: 10 }]])
  })
})

describe('commitWeeks', () => {
  it('lists the Monday weeks from the plan week to the end of the last plan month, labelled like the SIT file', () => {
    const weeks = commitWeeks('2026-10-14', ['2026-10', '2026-11'])
    expect(weeks[0]).toEqual({ monday: '2026-10-12', label: "Oct W3 (12 Oct)" })
    expect(weeks.map((w) => w.label)).toEqual([
      'Oct W3 (12 Oct)',
      'Oct W4 (19 Oct)',
      'Oct W5 (26 Oct)',
      'Nov W2 (2 Nov)',
      'Nov W3 (9 Nov)',
      'Nov W4 (16 Nov)',
      'Nov W5 (23 Nov)',
      'Dec W1 (30 Nov)', // the week holding 1 Dec; "Nov W6" would also be true but reads oddly
    ])
  })
})
describe('commitCartons', () => {
  it('adds up the cartons a row has from commits, leaving the file deliveries out', () => {
    const s = sku('A', 'P', {
      sit_arrivals: [
        { date: '2026-10-19', cartons: 5, source: 'sit' },
        { date: '2026-10-19', cartons: 10, source: 'commit' },
        { date: '2026-11-02', cartons: 2.5, source: 'commit' },
      ],
    })
    expect(commitCartons(s)).toBe(12.5)
    expect(commitCartons(sku('A', 'P', { sit_arrivals: [{ date: '2026-10-19', cartons: 5 }] }))).toBe(0)
    expect(commitCartons(sku('A', 'P', { sit_arrivals: null }))).toBe(0)
  })
})