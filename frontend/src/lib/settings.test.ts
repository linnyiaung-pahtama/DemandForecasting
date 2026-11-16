import { describe, expect, it } from 'vitest'
import { changedSettings, logValue, validateHolding, validateLeadTime, validateMoq, validateOrderCycle } from './settings'
import type { SupplierSettingView } from '../types'

const HOLDING_ERROR = 'Holding must be a whole number of days from 15 to 720, or blank.'

describe('validateHolding', () => {
  it('treats blank as not set', () => {
    expect(validateHolding('')).toEqual({ value: null, error: null })
    expect(validateHolding('   ')).toEqual({ value: null, error: null })
  })

  it('accepts whole days inside the range, including both ends', () => {
    expect(validateHolding('60')).toEqual({ value: 60, error: null })
    expect(validateHolding('15')).toEqual({ value: 15, error: null })
    expect(validateHolding('720')).toEqual({ value: 720, error: null })
    expect(validateHolding(' 45 ')).toEqual({ value: 45, error: null })
  })

  it('rejects out-of-range, fractional and non-numeric text', () => {
    for (const text of ['0', '14', '721', '45.5', '-1', 'abc', '1,5', '1e1', '0x10', 'NaN']) {
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
  holding_days: number | null,
  moq = 0,
  lead_time_days: number | null = null,
  order_cycle_weeks = 4,
): SupplierSettingView => ({ supplier, holding_days, moq, lead_time_days, order_cycle_weeks, sku_count: 1 })

describe('changedSettings', () => {
  it('returns the full row for suppliers with any field changed', () => {
    const original = [view('A', 60), view('B', null, 0, 14), view('C', 90, 100, 7), view('D', 90), view('E', 60)]
    const edited = {
      A: { holding_days: 75, moq: 0, lead_time_days: null, order_cycle_weeks: 4 },
      B: { holding_days: null, moq: 0, lead_time_days: null, order_cycle_weeks: 4 },
      C: { holding_days: 90, moq: 100, lead_time_days: 7, order_cycle_weeks: 4 },
      D: { holding_days: 90, moq: 8000, lead_time_days: null, order_cycle_weeks: 4 },
      E: { holding_days: 60, moq: 0, lead_time_days: null, order_cycle_weeks: 3 },
    }
    expect(changedSettings(original, edited)).toEqual([
      { supplier: 'A', holding_days: 75, moq: 0, lead_time_days: null, order_cycle_weeks: 4 },
      { supplier: 'B', holding_days: null, moq: 0, lead_time_days: null, order_cycle_weeks: 4 },
      { supplier: 'D', holding_days: 90, moq: 8000, lead_time_days: null, order_cycle_weeks: 4 },
      { supplier: 'E', holding_days: 60, moq: 0, lead_time_days: null, order_cycle_weeks: 3 },
    ])
  })

  it('skips suppliers that are not in the edited set and ignores unknown ones', () => {
    const edited = { Z: { holding_days: 150, moq: 0, lead_time_days: null, order_cycle_weeks: 4 } }
    expect(changedSettings([view('A', null)], edited)).toEqual([])
  })
})

describe('logValue', () => {
  it('formats each setting the way the change log shows it', () => {
    expect(logValue('lead_time_days', 14)).toBe('14 days')
    expect(logValue('lead_time_days', null)).toBe('blank')
    expect(logValue('moq', 0)).toBe('0')
    expect(logValue('moq', 8000)).toBe('8,000')
    expect(logValue('holding_days', null)).toBe('not set')
    expect(logValue('holding_days', 60)).toBe('60 days')
    // lines written before the holding moved to days keep reading in months
    expect(logValue('holding_months', null)).toBe('not set')
    expect(logValue('holding_months', 1.5)).toBe('1.5 months')
    expect(logValue('order_cycle_weeks', 4)).toBe('4 weeks')
    expect(logValue('order_cycle_weeks', 1)).toBe('1 week')
    // lines written before the cycle moved to weeks keep reading in months
    expect(logValue('order_cycle_months', 3)).toBe('3 months')
    expect(logValue('order_cycle_months', 1)).toBe('1 month')
  })
})
const CYCLE_ERROR = 'Order cycle must be a whole number of weeks from 1 to 52.'

describe('validateOrderCycle', () => {
  it('accepts whole weeks from 1 to 52', () => {
    expect(validateOrderCycle('1')).toEqual({ value: 1, error: null })
    expect(validateOrderCycle(' 4 ')).toEqual({ value: 4, error: null })
    expect(validateOrderCycle('52')).toEqual({ value: 52, error: null })
  })

  it('rejects blank, out-of-range, fractional and non-numeric text', () => {
    for (const text of ['', ' ', '0', '53', '1.5', '-1', 'abc', '1e1']) {
      expect(validateOrderCycle(text)).toEqual({ value: null, error: CYCLE_ERROR })
    }
  })
})