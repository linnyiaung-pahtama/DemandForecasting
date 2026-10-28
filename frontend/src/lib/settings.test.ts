import { describe, expect, it } from 'vitest'
import { changedHoldings, validateHolding } from './settings'
import type { SupplierSettingView } from '../types'

const HOLDING_ERROR = 'Holding must be a number from 0.5 to 24 months, or blank.'

describe('validateHolding', () => {
  it('treats blank as not set', () => {
    expect(validateHolding('')).toEqual({ value: null, error: null })
    expect(validateHolding('   ')).toEqual({ value: null, error: null })
  })

  it('accepts decimals inside the range, including both ends', () => {
    expect(validateHolding('1.5')).toEqual({ value: 1.5, error: null })
    expect(validateHolding('0.5')).toEqual({ value: 0.5, error: null })
    expect(validateHolding('24')).toEqual({ value: 24, error: null })
    expect(validateHolding(' 3 ')).toEqual({ value: 3, error: null })
  })

  it('rejects out-of-range and non-numeric text', () => {
    for (const text of ['0', '0.4', '25', '-1', 'abc', '1,5', '1e1', '0x10', 'NaN']) {
      expect(validateHolding(text)).toEqual({ value: null, error: HOLDING_ERROR })
    }
  })
})

const view = (supplier: string, holding_months: number | null): SupplierSettingView => ({
  supplier,
  holding_months,
  sku_count: 1,
  max_lead_time_days: null,
})

describe('changedHoldings', () => {
  it('returns only changed rows, with a cleared row as null', () => {
    const original = [view('A', 2), view('B', null), view('C', 3), view('D', 3)]
    const edited = { A: 2.5, B: null, C: null, D: 3 }
    expect(changedHoldings(original, edited)).toEqual([
      { supplier: 'A', holding_months: 2.5 },
      { supplier: 'C', holding_months: null },
    ])
  })

  it('includes a newly set holding and ignores unknown suppliers', () => {
    expect(changedHoldings([view('A', null)], { A: 1, Z: 5 })).toEqual([{ supplier: 'A', holding_months: 1 }])
  })
})
