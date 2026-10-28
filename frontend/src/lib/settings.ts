import type { SupplierHolding, SupplierSettingView } from '../types'

export const HOLDING_MIN = 0.5
export const HOLDING_MAX = 24

const HOLDING_ERROR = `Holding must be a number from ${HOLDING_MIN} to ${HOLDING_MAX} months, or blank.`

// Plain decimal notation only, so "1e1" and "0x10" are rejected rather than silently parsed.
const DECIMAL = /^(\d+(\.\d*)?|\.\d+)$/

/** Parses one holding input. Blank means "not set" (null, no error). */
export function validateHolding(text: string): { value: number | null; error: string | null } {
  const trimmed = text.trim()
  if (trimmed === '') return { value: null, error: null }
  const value = DECIMAL.test(trimmed) ? Number(trimmed) : NaN
  if (!Number.isFinite(value) || value < HOLDING_MIN || value > HOLDING_MAX) {
    return { value: null, error: HOLDING_ERROR }
  }
  return { value, error: null }
}

/**
 * The suppliers whose edited holding differs from the loaded value, as holdings to save.
 * Values are compared as parsed numbers; a cleared row is included with `holding_months: null`.
 */
export function changedHoldings(
  original: SupplierSettingView[],
  edited: Record<string, number | null>,
): SupplierHolding[] {
  const out: SupplierHolding[] = []
  for (const o of original) {
    if (!(o.supplier in edited)) continue
    const value = edited[o.supplier]
    if (value !== o.holding_months) out.push({ supplier: o.supplier, holding_months: value })
  }
  return out
}
