import { describe, it, expect } from 'vitest'
import { groupWarnings } from './warnings'
import type { ParseWarning } from '../types'

const w = (sap_code: string | null, message: string, column: string | null = null): ParseWarning => ({
  sap_code,
  column,
  message,
})

describe('groupWarnings', () => {
  it('separates file-level warnings, labelled by source, from per-SKU ones', () => {
    const g = groupWarnings(
      [w(null, 'No forecast column for Nov 2026 — counted as missing'), w('A1', 'negative stock')],
      [w(null, 'No sales rows for Aug 2026 - counted as missing'), w('A2', 'non-numeric Qty'), w('A3', 'x')],
    )
    expect(g.fileLevel).toEqual([
      { source: 'Data file', warning: w(null, 'No forecast column for Nov 2026 — counted as missing') },
      { source: 'Sales export', warning: w(null, 'No sales rows for Aug 2026 - counted as missing') },
    ])
    expect(g.perSku.map((x) => [x.source, x.warning.sap_code])).toEqual([
      ['Data file', 'A1'],
      ['Sales export', 'A2'],
      ['Sales export', 'A3'],
    ])
  })

  it('returns empty groups when there are no warnings', () => {
    expect(groupWarnings([], [])).toEqual({ fileLevel: [], perSku: [] })
  })
})
