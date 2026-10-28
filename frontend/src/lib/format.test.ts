import { describe, it, expect } from 'vitest'
import { fmtDate, fmtQty, monthLabel } from './format'

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
