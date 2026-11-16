import { describe, it, expect } from 'vitest'
import { filterSkus } from './filters'
import type { SkuFilter } from './filters'
import type { SkuResult, SkuStatus } from '../types'

function sku(
  code: string,
  supplier: string,
  status: SkuStatus,
  order_qty: number | null,
  extra: Partial<SkuResult> = {},
): SkuResult {
  return {
    sap_code: code,
    supplier,
    description: `item ${code}`,
    status,
    order_qty,
    zero_forecast: false,
    ...extra,
  } as SkuResult
}

const skus = [
  sku('1', 'B', 'NO_ORDER_NEEDED', 0),
  sku('2', 'A', 'TO_ORDER', 50),
  sku('3', 'A', 'HOLDING_NOT_SET', null),
  sku('4', 'B', 'TO_ORDER', 300, { zero_forecast: true }),
  sku('5', 'A', 'NO_DEMAND_DATA', 0),
  sku('6', 'A', 'TO_ORDER', 50, { description: 'alpha' }),
]
const none: SkuFilter = { supplier: null, status: null, zeroForecastOnly: false, search: '' }
const codes = (rows: SkuResult[]) => rows.map((s) => s.sap_code)

describe('filterSkus', () => {
  it('sorts by status, then order qty descending, then supplier, then description', () => {
    // TO_ORDER: 4 (300), then 6 and 2 (50 each, same supplier, "alpha" before "item 2")
    expect(codes(filterSkus(skus, none))).toEqual(['4', '6', '2', '3', '5', '1'])
  })

  it('puts a null order qty after numbers within the same status', () => {
    const rows = [sku('a', 'A', 'HOLDING_NOT_SET', null), sku('b', 'A', 'HOLDING_NOT_SET', 0)]
    expect(codes(filterSkus(rows, none))).toEqual(['b', 'a'])
  })

  it('does not mutate its input', () => {
    const before = codes(skus)
    filterSkus(skus, none)
    expect(codes(skus)).toEqual(before)
  })

  it('filters by supplier', () => {
    expect(codes(filterSkus(skus, { ...none, supplier: 'B' }))).toEqual(['4', '1'])
  })

  it('filters by status', () => {
    expect(codes(filterSkus(skus, { ...none, status: 'TO_ORDER' }))).toEqual(['4', '6', '2'])
  })

  it('filters to zero-forecast SKUs only', () => {
    expect(codes(filterSkus(skus, { ...none, zeroForecastOnly: true }))).toEqual(['4'])
  })

  it('searches SAP code and description, ignoring case and surrounding spaces', () => {
    expect(codes(filterSkus(skus, { ...none, search: ' ALPHA ' }))).toEqual(['6'])
    expect(codes(filterSkus(skus, { ...none, search: 'item 3' }))).toEqual(['3'])
  })

  it('combines filters', () => {
    expect(codes(filterSkus(skus, { ...none, supplier: 'A', status: 'TO_ORDER' }))).toEqual(['6', '2'])
  })

  it('filters and sorts on the order plan status and quantity in plan mode', () => {
    const rows = [
      sku('p', 'A', 'NO_ORDER_NEEDED', 0, { plan_status: 'TO_ORDER', plan_order_qty: 200 }),
      sku('q', 'A', 'TO_ORDER', 50, { plan_status: 'TO_ORDER', plan_order_qty: 400 }),
      sku('r', 'A', 'TO_ORDER', 90, { plan_status: 'NO_ORDER_NEEDED', plan_order_qty: 0 }),
    ]
    expect(codes(filterSkus(rows, { ...none, status: 'TO_ORDER' }))).toEqual(['r', 'q'])
    expect(codes(filterSkus(rows, { ...none, status: 'TO_ORDER' }, 'plan'))).toEqual(['q', 'p'])
    expect(codes(filterSkus(rows, none, 'plan'))).toEqual(['q', 'p', 'r'])
  })
})

describe('city filter', () => {
  it('keeps only the chosen city, and every row with no city filter', () => {
    const rows = [
      sku('A', 'P', 'TO_ORDER', 5, { city: 'YGN' }),
      sku('A', 'P', 'TO_ORDER', 3, { city: 'MDY' }),
      sku('B', 'P', 'TO_ORDER', 1, { city: 'YGN' }),
    ]
    const base = { supplier: null, status: null, zeroForecastOnly: false, search: '' }
    expect(filterSkus(rows, { ...base, city: 'MDY' }).map((s) => [s.sap_code, s.city])).toEqual([['A', 'MDY']])
    expect(filterSkus(rows, { ...base, city: null })).toHaveLength(3)
    expect(filterSkus(rows, base)).toHaveLength(3)
  })
})