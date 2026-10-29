import type { SupplierSettings, SupplierSettingView } from '../types'

export const HOLDING_MIN = 0.5
export const HOLDING_MAX = 24
export const LEAD_TIME_MAX = 365

const HOLDING_ERROR = `Holding must be a number from ${HOLDING_MIN} to ${HOLDING_MAX} months, or blank.`
const MOQ_ERROR = 'MOQ must be a whole number of cartons, 0 or more.'
const LEAD_ERROR = `Lead time must be a whole number of days from 0 to ${LEAD_TIME_MAX}, or blank.`

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

/** Parses one MOQ input: a whole number of cartons, 0 or more. Thousands separators ("8,000") are allowed; blank is not. */
export function validateMoq(text: string): Parsed {
  const digits = text.replace(/[,\s]/g, '')
  if (!WHOLE.test(digits)) return { value: null, error: MOQ_ERROR }
  return { value: Number(digits), error: null }
}

/** Parses one lead-time input: whole days from 0 to 365. Blank means "not set" (null, no error). */
export function validateLeadTime(text: string): Parsed {
  const trimmed = text.trim()
  if (trimmed === '') return { value: null, error: null }
  const value = WHOLE.test(trimmed) ? Number(trimmed) : NaN
  if (!Number.isFinite(value) || value > LEAD_TIME_MAX) return { value: null, error: LEAD_ERROR }
  return { value, error: null }
}

export type EditedSettings = Omit<SupplierSettings, 'supplier' | 'moq'> & { moq: number }

/**
 * The suppliers whose edited holding, MOQ or lead time differs from the loaded values, as full rows to save.
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
    if (e.holding_months !== o.holding_months || e.moq !== o.moq || e.lead_time_days !== o.lead_time_days) {
      out.push({ supplier: o.supplier, holding_months: e.holding_months, moq: e.moq, lead_time_days: e.lead_time_days })
    }
  }
  return out
}
