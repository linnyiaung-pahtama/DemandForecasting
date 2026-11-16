import { describe, expect, it } from 'vitest'
import { commitProblem, fromCommits, toCommits, type CommitLine } from './commits'

const codes = new Set(['A1', 'B2'])
const weeks = new Set(['2026-10-12', '2026-10-19'])
const line = (over: Partial<CommitLine> = {}): CommitLine => ({
  sap_code: 'A1',
  cartons: '40',
  arrival_week: '2026-10-19',
  region: 'YGN',
  ...over,
})

describe('commitProblem', () => {
  it('is null when every line is complete, and with no lines', () => {
    expect(commitProblem([line(), line({ sap_code: 'B2', region: 'MDY' })], codes, weeks)).toBeNull()
    expect(commitProblem([], codes, weeks)).toBeNull()
  })

  it('names the first incomplete line', () => {
    expect(commitProblem([line(), line({ sap_code: 'ZZ' })], codes, weeks)).toBe(
      'Commit 2: choose a SAP code from the Sales Forecast file.',
    )
    expect(commitProblem([line({ cartons: '0' })], codes, weeks)).toBe('Commit 1: enter cartons above 0.')
    expect(commitProblem([line({ cartons: 'abc' })], codes, weeks)).toBe('Commit 1: enter cartons above 0.')
    expect(commitProblem([line({ arrival_week: '' })], codes, weeks)).toBe('Commit 1: choose an arrival week.')
    expect(commitProblem([line({ arrival_week: '2026-10-05' })], codes, weeks)).toBe(
      'Commit 1: choose an arrival week.',
    )
  })

  it('takes the code from a picked "code — description" entry', () => {
    expect(commitProblem([line({ sap_code: ' A1 — Noodles (Acme)' })], codes, weeks)).toBeNull()
  })
})

describe('toCommits', () => {
  it('turns the lines into commits for the API', () => {
    expect(toCommits([line({ sap_code: 'A1 — Noodles (Acme)', cartons: '1,250.5' })])).toEqual([
      { sap_code: 'A1', cartons: 1250.5, arrival_week: '2026-10-19', region: 'YGN' },
    ])
  })
})

describe('fromCommits', () => {
  it('turns saved commits back into editor lines, and round-trips with toCommits', () => {
    const saved = [{ sap_code: 'A1', cartons: 1250.5, arrival_week: '2026-10-19', region: 'MDY' as const }]
    expect(fromCommits(saved)).toEqual([{ sap_code: 'A1', cartons: '1250.5', arrival_week: '2026-10-19', region: 'MDY' }])
    expect(toCommits(fromCommits(saved))).toEqual(saved)
  })
})