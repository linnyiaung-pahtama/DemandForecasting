export interface SettingValidation {
  errors: string[]
  warnings: string[]
}

function validLevel(n: number): boolean {
  return Number.isInteger(n) && n >= 1 && n <= 365
}

/** Checks one supplier's reorder/target levels; maxLeadTime is the longest lead time among its SKUs. */
export function validateSetting(
  s: { reorder_days: number; target_days: number },
  maxLeadTime: number | null,
): SettingValidation {
  const errors: string[] = []
  const warnings: string[] = []
  const reorderOk = validLevel(s.reorder_days)
  const targetOk = validLevel(s.target_days)
  if (!reorderOk) errors.push('Reorder level must be a whole number from 1 to 365.')
  if (!targetOk) errors.push('Target level must be a whole number from 1 to 365.')
  if (reorderOk && targetOk && s.target_days <= s.reorder_days) {
    errors.push('Target level must be higher than reorder level.')
  }
  if (maxLeadTime !== null && maxLeadTime >= s.reorder_days) {
    warnings.push(
      `Some SKUs have a lead time of ${maxLeadTime} days, at or above this reorder level, so they will run out before orders arrive.`,
    )
  }
  return { errors, warnings }
}
