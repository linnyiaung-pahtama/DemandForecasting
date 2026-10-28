import { describe, it, expect } from 'vitest'
import { fmtDate, fmtQty, monthLabel, orderExplanation, statusLabel } from './format'
import type { DemandValue, SkuResult } from '../types'

describe('monthLabel', () => {
  it('formats a YYYY-MM key', () => {
    expect(monthLabel('2026-07')).toBe('Jul 2026')
    expect(monthLabel('2026-12')).toBe('Dec 2026')
  })

  it('returns an unrecognised key unchanged', () => {
    expect(monthLabel('nope')).toBe('nope')
    expect(monthLabel('2026-13')).toBe('2026-13')
  })
})

describe('fmtDate', () => {
  it('formats an ISO date', () => {
    expect(fmtDate('2026-10-12')).toBe('12 Oct 2026')
  })
})

describe('fmtQty', () => {
  it('rounds and groups thousands', () => {
    expect(fmtQty(1234.4)).toBe('1,234')
    expect(fmtQty(2.5)).toBe('2.5')
  })
})

describe('statusLabel', () => {
  it('names each status', () => {
    expect(statusLabel('TO_ORDER')).toBe('To order')
    expect(statusLabel('NO_ORDER_NEEDED')).toBe('No order needed')
    expect(statusLabel('HOLDING_NOT_SET')).toBe('Holding not set')
    expect(statusLabel('NO_DEMAND_DATA')).toBe('No demand data')
  })
})

const MONTHS = ['2026-07', '2026-08', '2026-09', '2026-10', '2026-11', '2026-12']

function demand(values: (number | null)[]): DemandValue[] {
  return values.map((value, i) => ({
    month: MONTHS[i],
    source: i < 3 ? 'actual' : 'forecast',
    value,
    valid: value !== null && value > 0,
  }))
}

// The spec's worked example: buffer 120, holding 3, available 260, MOQ 150, lead 61 days.
const worked: SkuResult = {
  sap_code: '1001',
  supplier: 'Acme',
  description: 'Widget',
  packing_size: 12,
  lead_time_days: 61,
  moq: 150,
  sellable: 200,
  sit: 60,
  available: 260,
  demand_values: demand([100, 120, 110, 130, 140, 120]),
  valid_count: 6,
  buffer: 120,
  holding_months: 3,
  target: 360,
  required: 100,
  order_qty: 150,
  moq_applied: true,
  stock_cover_months: 260 / 120,
  next_calc_date: '2026-12-14',
  status: 'TO_ORDER',
  zero_forecast: false,
}

describe('orderExplanation', () => {
  it('writes out the worked example step by step', () => {
    expect(orderExplanation(worked, '2026-10-14')).toEqual([
      'Buffer = (100 + 120 + 110 + 130 + 140 + 120) ÷ 6 = 120 a month',
      'Target = 120 × 3 months = 360',
      'Available = 200 sellable + 60 SIT = 260',
      'Required = 360 − 260 = 100',
      'MOQ check: 100 is below the MOQ of 150, so the order is 150',
      'Stock cover = 260 ÷ 120 = 2.2 months',
      'Next calculation date = 14 Oct 2026 + 61 days lead time = 14 Dec 2026',
    ])
  })

  it('leaves skipped values out of the sum and divides by the valid count', () => {
    const r: SkuResult = {
      ...worked,
      demand_values: demand([100, 0, null, 130, -5, 100]),
      valid_count: 3,
      buffer: 110,
      target: 330,
      required: 70,
      moq_applied: false,
      order_qty: 70,
    }
    const lines = orderExplanation(r, '2026-10-14')
    expect(lines[0]).toBe('Buffer = (100 + 130 + 100) ÷ 3 = 110 a month')
    expect(lines.some((l) => l.startsWith('MOQ check'))).toBe(false)
  })

  it('replaces target, required and MOQ lines when holding is not set', () => {
    const r: SkuResult = {
      ...worked,
      holding_months: null,
      target: null,
      required: null,
      order_qty: null,
      moq_applied: false,
      status: 'HOLDING_NOT_SET',
    }
    expect(orderExplanation(r, '2026-10-14')).toEqual([
      'Buffer = (100 + 120 + 110 + 130 + 140 + 120) ÷ 6 = 120 a month',
      'Holding not set for Acme — no order calculated',
      'Available = 200 sellable + 60 SIT = 260',
      'Stock cover = 260 ÷ 120 = 2.2 months',
      'Next calculation date = 14 Oct 2026 + 61 days lead time = 14 Dec 2026',
    ])
  })

  it('explains a SKU with no valid demand values in one line', () => {
    const r: SkuResult = {
      ...worked,
      demand_values: demand([0, null, -3, 0, 0, null]),
      valid_count: 0,
      buffer: null,
      target: 0,
      required: 0,
      order_qty: 0,
      moq_applied: false,
      stock_cover_months: null,
      status: 'NO_DEMAND_DATA',
    }
    expect(orderExplanation(r, '2026-10-14')).toEqual([
      'No valid demand values (all 6 months are zero, negative or missing)',
    ])
  })

  it('says so when available already covers the target', () => {
    const r: SkuResult = {
      ...worked,
      sellable: 400,
      available: 460,
      required: 0,
      order_qty: 0,
      moq_applied: false,
      stock_cover_months: 460 / 120,
      status: 'NO_ORDER_NEEDED',
    }
    const lines = orderExplanation(r, '2026-10-14')
    expect(lines).toContain('Required = 0 (available already covers the target)')
    expect(lines.some((l) => l.startsWith('MOQ check'))).toBe(false)
  })

  it('notes rounding up when the gap is not a whole carton count', () => {
    const r: SkuResult = {
      ...worked,
      buffer: 120.4,
      target: 361.2,
      required: 102,
      moq: 0,
      moq_applied: false,
      order_qty: 102,
    }
    expect(orderExplanation(r, '2026-10-14')).toContain(
      'Required = 361 − 260 = 102 (rounded up to whole cartons)',
    )
  })

  it('shows decimal holding as stored', () => {
    const r: SkuResult = { ...worked, holding_months: 1.5, target: 180 }
    expect(orderExplanation(r, '2026-10-14')[1]).toBe('Target = 120 × 1.5 months = 180')
  })

  it('handles a missing lead time', () => {
    const r: SkuResult = { ...worked, lead_time_days: null, next_calc_date: null }
    const lines = orderExplanation(r, '2026-10-14')
    expect(lines[lines.length - 1]).toBe('Next calculation date: no lead time')
  })
})
