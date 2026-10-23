import { describe, it, expect } from 'vitest'
import { orderReason } from './format'
import type { OrderReason, PlannedOrder } from '../types'

const order = (qty: number, reason: Partial<OrderReason>): PlannedOrder => ({
  order_date: '2026-10-12',
  arrival_date: '2026-10-19',
  qty,
  reason: {
    on_hand: 85.1,
    on_order: 0,
    inventory_position: 85.1,
    stock_at_arrival: 54.4,
    reorder_qty: 87.5,
    target_qty: 130.4,
    raw_qty: 45.3,
    moq_applied: false,
    shelf_life_cap: null,
    cap_applied: false,
    ...reason,
  },
})

describe('orderReason', () => {
  it('describes a plain order', () => {
    expect(orderReason(order(46, {}))).toBe(
      'On 12 Oct 2026 stock + on order = 85, below reorder level 88. ' +
        'Ordering 46 to reach target 130. Expected stock when it arrives: 54.',
    )
  })

  it('mentions MOQ when the quantity was raised to it', () => {
    expect(orderReason(order(100, { moq_applied: true }))).toBe(
      'On 12 Oct 2026 stock + on order = 85, below reorder level 88. ' +
        'Ordering 100 to reach target 130. (raised to MOQ) Expected stock when it arrives: 54.',
    )
  })

  it('mentions the shelf-life cap when it applied', () => {
    expect(orderReason(order(30, { cap_applied: true, shelf_life_cap: 30.2 }))).toBe(
      'On 12 Oct 2026 stock + on order = 85, below reorder level 88. ' +
        'Ordering 30 to reach target 130. (capped by shelf life at 30) Expected stock when it arrives: 54.',
    )
  })
})
