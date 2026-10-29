import { describe, expect, it } from 'vitest'
import { changedSettings, logValue, validateHolding, validateLeadTime, validateMoq } from './settings'
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

const MOQ_ERROR = 'MOQ must be a whole number of cartons, 0 or more.'
const LEAD_ERROR = 'Lead time must be a whole number of days from 0 to 365, or blank.'

describe('validateMoq', () => {
  it('accepts whole numbers of 0 or more, with thousands separators', () => {
    expect(validateMoq('8,000')).toEqual({ value: 8000, error: null })
    expect(validateMoq(' 0 ')).toEqual({ value: 0, error: null })
    expect(validateMoq('150')).toEqual({ value: 150, error: null })
  })

  it('rejects blank, negative, fractional and non-numeric text', () => {
    for (const text of ['', '  ', '-1', '1.5', 'abc', '1e3', '8,00', '1 0 0', '80,00,0', ',800']) {
      expect(validateMoq(text)).toEqual({ value: null, error: MOQ_ERROR })
    }
  })
})

describe('validateLeadTime', () => {
  it('treats blank as not set and accepts 0 to 365 days', () => {
    expect(validateLeadTime('')).toEqual({ value: null, error: null })
    expect(validateLeadTime('14')).toEqual({ value: 14, error: null })
    expect(validateLeadTime('0')).toEqual({ value: 0, error: null })
    expect(validateLeadTime('365')).toEqual({ value: 365, error: null })
  })

  it('rejects out-of-range, fractional and non-numeric text', () => {
    for (const text of ['366', '-1', '2.5', 'abc', '1e2']) {
      expect(validateLeadTime(text)).toEqual({ value: null, error: LEAD_ERROR })
    }
  })
})

const view = (
  supplier: string,
  holding_months: number | null,
  moq = 0,
  lead_time_days: number | null = null,
): SupplierSettingView => ({ supplier, holding_months, moq, lead_time_days, sku_count: 1 })

describe('changedSettings', () => {
  it('returns the full row for suppliers with any field changed', () => {
    const original = [view('A', 2), view('B', null, 0, 14), view('C', 3, 100, 7), view('D', 3)]
    const edited = {
      A: { holding_months: 2.5, moq: 0, lead_time_days: null },
      B: { holding_months: null, moq: 0, lead_time_days: null },
      C: { holding_months: 3, moq: 100, lead_time_days: 7 },
      D: { holding_months: 3, moq: 8000, lead_time_days: null },
    }
    expect(changedSettings(original, edited)).toEqual([
      { supplier: 'A', holding_months: 2.5, moq: 0, lead_time_days: null },
      { supplier: 'B', holding_months: null, moq: 0, lead_time_days: null },
      { supplier: 'D', holding_months: 3, moq: 8000, lead_time_days: null },
    ])
  })

  it('skips suppliers that are not in the edited set and ignores unknown ones', () => {
    const edited = { Z: { holding_months: 5, moq: 0, lead_time_days: null } }
    expect(changedSettings([view('A', null)], edited)).toEqual([])
  })
})

describe('logValue', () => {
  it('formats each setting the way the change log shows it', () => {
    expect(logValue('lead_time_days', 14)).toBe('14 days')
    expect(logValue('lead_time_days', null)).toBe('blank')
    expect(logValue('moq', 0)).toBe('0')
    expect(logValue('moq', 8000)).toBe('8,000')
    expect(logValue('holding_months', null)).toBe('not set')
    expect(logValue('holding_months', 2)).toBe('2')
    expect(logValue('holding_months', 1.5)).toBe('1.5')
  })
})