import { it, expect } from 'vitest'
import { validateSetting } from './settings'

it('accepts valid levels', () => {
  expect(validateSetting({ reorder_days: 45, target_days: 60 }, 30)).toEqual({ errors: [], warnings: [] })
})
it('rejects target not above reorder and out-of-range values', () => {
  expect(validateSetting({ reorder_days: 30, target_days: 30 }, null).errors)
    .toContain('Target level must be higher than reorder level.')
  expect(validateSetting({ reorder_days: 0, target_days: 30 }, null).errors).toHaveLength(1)
  expect(validateSetting({ reorder_days: 10.5, target_days: 30 }, null).errors).toHaveLength(1)
})
it('warns when lead time reaches the reorder level', () => {
  expect(validateSetting({ reorder_days: 20, target_days: 30 }, 30).warnings).toHaveLength(1)
})
