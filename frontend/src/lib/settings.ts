import { fmtMonths, fmtQty } from './format'
import type { SettingField, SupplierSettings, SupplierSettingView } from '../types'

export const HOLDING_MIN = 0.5
export const HOLDING_MAX = 24
export const LEAD_TIME_MAX = 365
export const ORDER_CYCLE_MIN = 1
export const ORDER_CYCLE_MAX = 12

const HOLDING_ERROR = `Holding must be a number from ${HOLDING_MIN} to ${HOLDING_MAX} months, or blank.`
const MOQ_ERROR = 'MOQ must be a whole number of cartons, 0 or more.'
const LEAD_ERROR = `Lead time must be a whole number of days from 0 to ${LEAD_TIME_MAX}, or blank.`
const CYCLE_ERROR = `Order cycle must be a whole number of months from ${ORDER_CYCLE_MIN} to ${ORDER_CYCLE_MAX}.`

// Plain decimal notation only, so "1e1" and "0x10" are rejected rather than silently parsed.
const DECIMAL = /^(\d+(\.\d*)?|\.\d+)$/
const WHOLE = /^\d+$/

export interface Parsed {
  value: number | null
  error: string | null
}

/** Parses one holding input. Blank means "not set" (null, no error). */
export function validateHolding(text: string): Parsed {
  const trimmed = text.trim()
  if (trimmed === '') return { value: null, error: null }
  const value = DECIMAL.test(trimmed) ? Number(trimmed) : NaN
  if (!Number.isFinite(value) || value < HOLDING_MIN || value > HOLDING_MAX) {
    return { value: null, error: HOLDING_ERROR }
  }
  return { value, error: null }
}

// Whole number, either plain ("8000") or with correctly grouped thousands ("8,000"), so a typo like "8,00" is an error.
const MOQ_TEXT = /^(\d+|\d{1,3}(,\d{3})+)$/

/** Parses one MOQ input: a whole number of cartons, 0 or more. Thousands separators ("8,000") are allowed; blank is not. */
export function validateMoq(text: string): Parsed {
  const trimmed = text.trim()
  if (!MOQ_TEXT.test(trimmed)) return { value: null, error: MOQ_ERROR }
  return { value: Number(trimmed.replace(/,/g, '')), error: null }
}

/**
 * One change-log value: holding in months ("not set" when blank), MOQ in cartons, lead time in days ("blank"),
 * order cycle in months.
 */
export function logValue(field: SettingField, value: number | null): string {
  if (value === null) return field === 'holding_months' ? 'not set' : 'blank'
  if (field === 'moq') return fmtQty(value)
  if (field === 'lead_time_days') return `${value} days`
  if (field === 'order_cycle_months') return `${value} month${value === 1 ? '' : 's'}`
  return fmtMonths(value)
}

/** Parses one order-cycle input: whole months from 1 to 12. Blank is an error: there is always a cycle. */
export function validateOrderCycle(text: string): Parsed {
  const trimmed = text.trim()
  const value = WHOLE.test(trimmed) ? Number(trimmed) : NaN
  if (!Number.isFinite(value) || value < ORDER_CYCLE_MIN || value > ORDER_CYCLE_MAX) {
    return { value: null, error: CYCLE_ERROR }
  }
  return { value, error: null }
}

/** Parses one lead-time input: whole days from 0 to 365. Blank means "not set" (null, no error). */
export function validateLeadTime(text: string): Parsed {
  const trimmed = text.trim()
  if (trimmed === '') return { value: null, error: null }
  const value = WHOLE.test(trimmed) ? Number(trimmed) : NaN
  if (!Number.isFinite(value) || value > LEAD_TIME_MAX) return { value: null, error: LEAD_ERROR }
  return { value, error: null }
}

export type EditedSettings = Omit<SupplierSettings, 'supplier' | 'moq' | 'order_cycle_months'> & {
  moq: number
  order_cycle_months: number
}

/**
 * The suppliers whose edited holding, MOQ, lead time or order cycle differs from the loaded values, as full rows to save.
 * Values are compared as parsed numbers; a cleared holding or lead time is included as null.
 */
export function changedSettings(
  original: SupplierSettingView[],
  edited: Record<string, EditedSettings>,
): SupplierSettings[] {
  const out: SupplierSettings[] = []
  for (const o of original) {
    const e = edited[o.supplier]
    if (!e) continue
    if (
      e.holding_months !== o.holding_months ||
      e.moq !== o.moq ||
      e.lead_time_days !== o.lead_time_days ||
      e.order_cycle_months !== o.order_cycle_months
    ) {
      out.push({
        supplier: o.supplier,
        holding_months: e.holding_months,
        moq: e.moq,
        lead_time_days: e.lead_time_days,
        order_cycle_months: e.order_cycle_months,
      })
    }
  }
  return out
}
