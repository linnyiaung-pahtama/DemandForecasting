import { describe, it, expect } from 'vitest'
import { groupWarnings, stockFileWarnings } from './warnings'
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

  it('puts stock warnings after the data and sales ones, labelled "Stock files"', () => {
    const g = groupWarnings(
      [w(null, 'data note')],
      [w(null, 'sales note')],
      [w(null, 'PG Expiry Check: 32 stock codes are not in the Data sheet; ignored'), w('A1', 'negative stock')],
    )
    expect(g.fileLevel.map((x) => [x.source, x.warning.message])).toEqual([
      ['Data file', 'data note'],
      ['Sales export', 'sales note'],
      ['Stock files', 'PG Expiry Check: 32 stock codes are not in the Data sheet; ignored'],
    ])
    expect(g.perSku.map((x) => [x.source, x.warning.sap_code])).toEqual([['Stock files', 'A1']])
  })

  it('still works with two arguments', () => {
    expect(groupWarnings([w(null, 'a')], [w('A1', 'b')])).toEqual({
      fileLevel: [{ source: 'Data file', warning: w(null, 'a') }],
      perSku: [{ source: 'Sales export', warning: w('A1', 'b') }],
    })
  })

  it('returns empty groups when there are no warnings', () => {
    expect(groupWarnings([], [])).toEqual({ fileLevel: [], perSku: [] })
  })
})

describe('stockFileWarnings', () => {
  it('keeps only the file-level warnings that start with a stock report name', () => {
    const list = [
      w(null, 'Stock columns in the Data sheet are ignored'),
      w(null, 'PG Expiry Check has no stock for any SKU in the Data sheet — check that it is the right report'),
      w('A1', 'PDG Stock List: a stock row for this SKU could not be read and was skipped'),
      w(null, 'PDG Stock List was printed on 2 Oct 2026, 10 days before the plan date'),
      w(null, 'No sales rows for Aug 2026'),
    ]
    expect(stockFileWarnings(list).map((x) => x.message)).toEqual([
      'PG Expiry Check has no stock for any SKU in the Data sheet — check that it is the right report',
      'PDG Stock List was printed on 2 Oct 2026, 10 days before the plan date',
    ])
  })
})
