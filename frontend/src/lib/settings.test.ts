import { it, expect } from 'vitest'
import { changedSettings, validateSetting } from './settings'

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

const view = (supplier: string, reorder_days: number, target_days: number, is_default: boolean) => ({
  supplier,
  reorder_days,
  target_days,
  is_default,
  max_lead_time_days: null,
  sku_count: 1,
})

it('changedSettings returns only rows whose levels differ', () => {
  const original = [view('A', 20, 30, true), view('B', 20, 30, true), view('C', 45, 60, false)]
  const edited = [
    { supplier: 'A', reorder_days: 25, target_days: 30 }, // changed
    { supplier: 'B', reorder_days: 20, target_days: 30 }, // unchanged default
    { supplier: 'C', reorder_days: 45, target_days: 60 }, // unchanged non-default
  ]
  expect(changedSettings(original, edited)).toEqual([
    { supplier: 'A', reorder_days: 25, target_days: 30, is_default: false },
  ])
  expect(changedSettings(original, edited.slice(1))).toEqual([])
})
