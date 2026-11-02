import { describe, it, expect } from 'vitest'
import {
  demandColumns,
  fmtDate,
  fmtQty,
  fmtTime,
  hasMonthly,
  isLegacyRun,
  monthLabel,
  monthlyTotal,
  orderExplanation,
  statusLabel,
} from './format'
import type { DemandValue, HoldingPlan, MonthPlan, SkuResult } from '../types'

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
  pg_sellable: null,
  pdg_sellable: null,
  pg_non_sellable: null,
  pdg_non_sellable: null,
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
  monthly: null,
  order_cycle_months: 1,
  order_plan: null,
  plan_order_up_to: null,
  plan_required: null,
  plan_order_qty: null,
  plan_moq_applied: false,
  plan_status: null,
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

  it('explains the order plan with the order-up-to level in plan mode', () => {
    // spec small example: cycle 3, order-up-to 120 × 5 = 600, required 340, no MOQ
    const r: SkuResult = {
      ...worked,
      moq: 0,
      moq_applied: false,
      order_qty: 100,
      order_cycle_months: 3,
      order_plan: [],
      plan_order_up_to: 600,
      plan_required: 340,
      plan_order_qty: 340,
      plan_moq_applied: false,
      plan_status: 'TO_ORDER',
    }
    const lines = orderExplanation(r, '2026-10-14', 'plan')
    expect(lines.slice(1, 4)).toEqual([
      'Order-up-to = 120 × (3 + 3 − 1) months = 600',
      'Available = 200 sellable + 60 SIT = 260',
      'Required = 600 − 260 = 340',
    ])
    expect(lines.some((l) => l.startsWith('Target') || l.startsWith('MOQ check'))).toBe(false)
    expect(orderExplanation(r, '2026-10-14')).toEqual(orderExplanation(r, '2026-10-14', 'forecast'))
  })

  it('asks for a recalculation, not "holding not set", when an older run has no order plan', () => {
    // worked has holding 3 but no order plan (order_plan and plan_* are null): saved before the order cycle
    expect(orderExplanation(worked, '2026-10-14', 'plan')).toEqual(['Recalculate to see the order plan.'])
  })

  it('uses the order plan MOQ check in plan mode', () => {
    const r: SkuResult = {
      ...worked,
      moq: 500,
      order_cycle_months: 3,
      order_plan: [],
      plan_order_up_to: 600,
      plan_required: 340,
      plan_order_qty: 500,
      plan_moq_applied: true,
      plan_status: 'TO_ORDER',
    }
    expect(orderExplanation(r, '2026-10-14', 'plan')).toContain(
      'MOQ check: 340 is below the MOQ of 500, so the order is 500',
    )
  })

  it('splits the available line into PG and PDG sellable when the breakdown is stored', () => {
    const r: SkuResult = { ...worked, pg_sellable: 150, pdg_sellable: 50 }
    expect(orderExplanation(r, '2026-10-14')).toContain('Available = 150 PG sellable + 50 PDG sellable + 60 SIT = 260')
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

  it('shows exact figures and the round-up for real data with fractional values', () => {
    // SKU 3102111001: actuals 2113/40, 1451/40, 1647/40 cartons; forecast 55 x 3.
    const r: SkuResult = {
      ...worked,
      sap_code: '3102111001',
      lead_time_days: 7,
      moq: 0,
      sellable: 22.15,
      sit: 16,
      available: 22.15 + 16,
      demand_values: demand([2113 / 40, 1451 / 40, 1647 / 40, 55, 55, 55]),
      valid_count: 6,
      buffer: 49.2125,
      holding_months: 3,
      target: 49.2125 * 3,
      required: 110,
      order_qty: 110,
      moq_applied: false,
      stock_cover_months: (22.15 + 16) / 49.2125,
      next_calc_date: '2026-10-19',
    }
    const lines = orderExplanation(r, '2026-10-12')
    expect(lines).toEqual([
      'Buffer = (52.825 + 36.275 + 41.175 + 55 + 55 + 55) ÷ 6 = 49.2125 a month',
      'Target = 49.2125 × 3 months = 147.6375',
      'Available = 22.15 sellable + 16 SIT = 38.15',
      'Required = 147.6375 − 38.15 = 109.4875, rounded up to 110',
      'Stock cover = 38.15 ÷ 49.2125 = 0.8 months',
      'Next calculation date = 12 Oct 2026 + 7 days lead time = 19 Oct 2026',
    ])
  })

  it('lists holding not set after no valid demand', () => {
    const r: SkuResult = {
      ...worked,
      demand_values: demand([0, null, -3, 0, 0, null]),
      valid_count: 0,
      buffer: null,
      holding_months: null,
      target: null,
      required: null,
      order_qty: null,
      moq_applied: false,
      stock_cover_months: null,
      status: 'HOLDING_NOT_SET',
    }
    expect(orderExplanation(r, '2026-10-14')).toEqual([
      'No valid demand values (all 6 months are zero, negative or missing)',
      'Holding not set for Acme — no order calculated',
    ])
  })

  it('says when the lead time is not valid', () => {
    const r: SkuResult = { ...worked, lead_time_days: -2, next_calc_date: null }
    const lines = orderExplanation(r, '2026-10-14')
    expect(lines[lines.length - 1]).toBe('Next calculation date: lead time of -2 days is not valid')
  })

  it('uses singular month and day for 1', () => {
    const r: SkuResult = { ...worked, holding_months: 1, target: 120, lead_time_days: 1, next_calc_date: '2026-10-15' }
    const lines = orderExplanation(r, '2026-10-14')
    expect(lines[1]).toBe('Target = 120 × 1 month = 120')
    expect(lines[lines.length - 1]).toBe('Next calculation date = 14 Oct 2026 + 1 day lead time = 15 Oct 2026')
  })

  it('shows decimal holding as stored', () => {
    const r: SkuResult = { ...worked, holding_months: 1.5, target: 180 }
    expect(orderExplanation(r, '2026-10-14')[1]).toBe('Target = 120 × 1.5 months = 180')
  })

  it('handles a missing lead time', () => {
    const r: SkuResult = { ...worked, lead_time_days: null, next_calc_date: null }
    const lines = orderExplanation(r, '2026-10-14')
    expect(lines[lines.length - 1]).toBe('Next calculation date: lead time not set')
  })
})

describe('fmtTime', () => {
  it('returns HH:MM from an ISO date-time', () => {
    expect(fmtTime('2026-10-12T09:05:33')).toBe('09:05')
    expect(fmtTime('2026-10-12T21:40:00+08:00')).toBe('21:40')
  })

  it('returns an empty string when there is no time', () => {
    expect(fmtTime('2026-10-12')).toBe('')
  })
})

describe('isLegacyRun', () => {
  const plan = (moq: number | null): HoldingPlan => ({
    plan_date: '2026-10-12',
    actual_months: [],
    forecast_months: [],
    plan_months: [],
    skus: [],
    settings_used: [
      { supplier: 'A', holding_months: 2, moq: 0, lead_time_days: 14, order_cycle_months: 1 },
      { supplier: 'B', holding_months: null, moq, lead_time_days: null, order_cycle_months: 1 },
    ],
    blocked_suppliers: [],
    counts: {},
    plan_counts: null,
  })

  it('is true when a supplier in settings_used has no recorded MOQ (saved before supplier MOQ/lead time)', () => {
    expect(isLegacyRun(plan(null))).toBe(true)
  })

  it('is false when every supplier has a recorded MOQ', () => {
    expect(isLegacyRun(plan(0))).toBe(false)
  })
})

const month = (key: string, order: number | null): MonthPlan => ({
  month: key,
  opening: 0,
  demand: 0,
  order,
  moq_applied: false,
  closing: 0,
  order_month: true,
})

describe('monthlyTotal', () => {
  it('sums the monthly orders', () => {
    const r = { ...worked, monthly: [month('2026-10', 150), month('2026-11', 0), month('2026-12', 150)] }
    expect(monthlyTotal(r)).toBe(300)
  })

  it('is null when holding is not set or there is no 12-month plan', () => {
    expect(monthlyTotal({ ...worked, holding_months: null, monthly: [month('2026-10', null)] })).toBeNull()
    expect(monthlyTotal({ ...worked, monthly: null })).toBeNull()
  })
})

describe('demandColumns', () => {
  it('lines up the actual then forecast values with the plan months', () => {
    const cols = demandColumns(worked, ['2026-07', '2026-08', '2026-09'], ['2026-10', '2026-11', '2026-12'])
    expect(cols.map((d) => d?.value)).toEqual([100, 120, 110, 130, 140, 120])
    expect(cols.map((d) => d?.source)).toEqual(['actual', 'actual', 'actual', 'forecast', 'forecast', 'forecast'])
  })

  it('is null for a month the SKU has no value for', () => {
    const r = { ...worked, demand_values: worked.demand_values.filter((d) => d.month !== '2026-08') }
    expect(demandColumns(r, ['2026-07', '2026-08'], []).map((d) => d?.value ?? null)).toEqual([100, null])
  })

  it('keeps an actual and a forecast for the same month apart', () => {
    const r = {
      ...worked,
      demand_values: [
        { month: '2026-10', source: 'actual' as const, value: 5, valid: true },
        { month: '2026-10', source: 'forecast' as const, value: 9, valid: true },
      ],
    }
    expect(demandColumns(r, ['2026-10'], ['2026-10']).map((d) => d?.value)).toEqual([5, 9])
  })
})

describe('hasMonthly', () => {
  const plan = (skus: SkuResult[], planMonths: string[]): HoldingPlan => ({
    plan_date: '2026-10-12',
    actual_months: [],
    forecast_months: [],
    plan_months: planMonths,
    skus,
    settings_used: [],
    blocked_suppliers: [],
    counts: {},
    plan_counts: null,
  })
  const withMonths = { ...worked, monthly: [month('2026-10', 150)] }

  it('is true when the plan has months and every SKU carries them', () => {
    expect(hasMonthly(plan([withMonths, withMonths], ['2026-10']))).toBe(true)
  })

  it('is false for a plan saved before the 12-month plan', () => {
    expect(hasMonthly(plan([withMonths], []))).toBe(false)
    expect(hasMonthly(plan([withMonths, { ...worked, monthly: null }], ['2026-10']))).toBe(false)
  })
})