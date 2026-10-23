import { describe, it, expect } from 'vitest'
import { filterSkus, ordersInWindow } from './filters'
import type { OrderReason, SkuPlan } from '../types'

const order = (d: string) => ({ order_date: d, arrival_date: d, qty: 10, reason: {} as OrderReason })
const sku = (code: string, supplier: string, orders: string[], flags: string[] = []): SkuPlan =>
  ({ sap_code: code, supplier, description: `item ${code}`, orders: orders.map(order),
     flags: flags.map(c => ({ code: c, message: '' })) } as unknown as SkuPlan)

const skus = [sku('1', 'A', ['2026-11-20']), sku('2', 'B', ['2026-10-12'], ['ORDER_NOW']), sku('3', 'A', [])]
const none = { supplier: null, flag: null, dueWithinWeeks: null, search: '' }

describe('filterSkus', () => {
  it('sorts by next order date, SKUs without orders last', () => {
    expect(filterSkus(skus, none, '2026-10-12').map(s => s.sap_code)).toEqual(['2', '1', '3'])
  })
  it('filters by supplier, flag, window and search', () => {
    expect(filterSkus(skus, { ...none, supplier: 'A' }, '2026-10-12').map(s => s.sap_code)).toEqual(['1', '3'])
    expect(filterSkus(skus, { ...none, flag: 'ORDER_NOW' }, '2026-10-12').map(s => s.sap_code)).toEqual(['2'])
    expect(filterSkus(skus, { ...none, dueWithinWeeks: 4 }, '2026-10-12').map(s => s.sap_code)).toEqual(['2'])
    expect(filterSkus(skus, { ...none, search: 'ITEM 3' }, '2026-10-12').map(s => s.sap_code)).toEqual(['3'])
  })
  it('window is exclusive of planDate + 7*weeks', () => {
    expect(ordersInWindow(sku('9', 'A', ['2026-11-09']), '2026-10-12', 4)).toHaveLength(0)
    expect(ordersInWindow(sku('9', 'A', ['2026-11-08']), '2026-10-12', 4)).toHaveLength(1)
  })
})
