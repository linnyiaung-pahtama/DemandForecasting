import { describe, it, expect } from 'vitest'
import { groupWarnings, runOutWarnings, stockFileWarnings } from './warnings'
import type { ParseWarning, SkuResult } from '../types'

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
      { source: 'Sales Forecast file', warning: w(null, 'No forecast column for Nov 2026 — counted as missing') },
      { source: 'Actual Sales file', warning: w(null, 'No sales rows for Aug 2026 - counted as missing') },
    ])
    expect(g.perSku.map((x) => [x.source, x.warning.sap_code])).toEqual([
      ['Sales Forecast file', 'A1'],
      ['Actual Sales file', 'A2'],
      ['Actual Sales file', 'A3'],
    ])
  })

  it('puts stock warnings after the data and sales ones, labelled "Stock files"', () => {
    const g = groupWarnings(
      [w(null, 'data note')],
      [w(null, 'sales note')],
      [w(null, 'PG Expiry Check: 32 stock codes are not in the Data sheet; ignored'), w('A1', 'negative stock')],
    )
    expect(g.fileLevel.map((x) => [x.source, x.warning.message])).toEqual([
      ['Sales Forecast file', 'data note'],
      ['Actual Sales file', 'sales note'],
      ['Stock files', 'PG Expiry Check: 32 stock codes are not in the Data sheet; ignored'],
    ])
    expect(g.perSku.map((x) => [x.source, x.warning.sap_code])).toEqual([['Stock files', 'A1']])
  })

  it('labels the fourth list "Stock in Transit file", after the stock warnings', () => {
    const g = groupWarnings([], [], [w(null, 'stock note')], [w(null, 'sit note'), w('A1', 'sit flag')])
    expect(g.fileLevel.map((x) => [x.source, x.warning.message])).toEqual([
      ['Stock files', 'stock note'],
      ['Stock in Transit file', 'sit note'],
    ])
    expect(g.perSku.map((x) => [x.source, x.warning.sap_code])).toEqual([['Stock in Transit file', 'A1']])
  })

  it('still works with two arguments', () => {
    expect(groupWarnings([w(null, 'a')], [w('A1', 'b')])).toEqual({
      fileLevel: [{ source: 'Sales Forecast file', warning: w(null, 'a') }],
      perSku: [{ source: 'Actual Sales file', warning: w('A1', 'b') }],
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

describe('runOutWarnings', () => {
  it('turns each flagged SKU into a warning on its SAP code', () => {
    const skus = [
      { sap_code: 'A1', runs_out_on: '2026-10-17', runs_out_arrival: '2026-10-19' },
      { sap_code: 'A2', runs_out_on: null, runs_out_arrival: null },
    ] as SkuResult[]
    expect(runOutWarnings(skus)).toEqual([
      w('A1', 'runs out about 17 Oct, before its stock in transit arrives on 19 Oct'),
    ])
  })

  it('ignores older runs whose SKUs have no flag fields', () => {
    expect(runOutWarnings([{ sap_code: 'A1' } as SkuResult])).toEqual([])
  })
})
describe('runOutWarnings by city', () => {
  it('starts with the city for a city row', () => {
    const skus = [{ sap_code: 'A1', city: 'MDY', runs_out_on: '2026-10-17', runs_out_arrival: '2026-10-19' }] as SkuResult[]
    expect(runOutWarnings(skus)).toEqual([
      w('A1', 'Mandalay: runs out about 17 Oct, before its stock in transit arrives on 19 Oct'),
    ])
  })
})