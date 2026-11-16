import { useMemo, useState } from 'react'
import { errorText, saveCommits } from '../api'
import { commitProblem, fromCommits, toCommits, type CommitLine } from '../lib/commits'
import { cityLabel, fmtDate, fmtQty } from '../lib/format'
import { commitWeeks } from '../lib/mode'
import type { RunRecord, SkuOption } from '../types'
import CommitEditor from './CommitEditor'

interface Props {
  run: RunRecord
  selected: string | null // the plan page's selected row key (SAP code | region)
  onSelect: (key: string | null) => void
  onSaved: (run: RunRecord) => void // the plan, recalculated with the new commits
}

/**
 * A calculated plan's commits: a list (click a line to open that SKU's row), and Edit commits to add, change or
 * remove them. Saving recalculates the plan in place with the current principal settings.
 */
export default function CommitsPanel({ run, selected, onSelect, onSaved }: Props) {
  const commits = run.parsed.commits ?? []
  const result = run.result
  const [lines, setLines] = useState<CommitLine[] | null>(null) // null when not editing
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // One option per SKU of the plan (a SKU has a row per region).
  const skus = useMemo<SkuOption[]>(() => {
    const seen = new Map<string, SkuOption>()
    for (const s of result.skus) {
      if (!seen.has(s.sap_code)) seen.set(s.sap_code, { sap_code: s.sap_code, description: s.description, supplier: s.supplier })
    }
    return [...seen.values()]
  }, [result])
  const weeks = useMemo(() => commitWeeks(result.plan_date, result.plan_months), [result])
  const issue =
    lines === null
      ? null
      : commitProblem(lines, new Set(skus.map((s) => s.sap_code)), new Set(weeks.map((w) => w.monday)))

  async function onSave() {
    if (lines === null || issue) return
    setSaving(true)
    setError(null)
    try {
      onSaved(await saveCommits(run.id, toCommits(lines)))
      setLines(null)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <details className="warnings commits-panel" open={commits.length > 0 || lines !== null}>
      <summary>
        Commits <span className="badge">{commits.length}</span>
      </summary>
      <p className="muted">
        Stock agreed with a principal that isn&apos;t in the Stock in Transit file yet. Each counts as stock in
        transit arriving on the Monday of its week, in its region, so it isn&apos;t ordered again.
      </p>

      {lines === null ? (
        <>
          {commits.length > 0 ? (
            <table className="inner">
              <thead>
                <tr>
                  <th>SAP Code</th>
                  <th>Description</th>
                  <th>Principal</th>
                  <th>Region</th>
                  <th className="num">Cartons</th>
                  <th>Arrival week</th>
                </tr>
              </thead>
              <tbody>
                {commits.map((c, i) => {
                  const sku = skus.find((s) => s.sap_code === c.sap_code)
                  const key = `${c.sap_code}|${c.region}`
                  return (
                    <tr
                      key={i}
                      className={`clickable${key === selected ? ' selected' : ''}`}
                      onClick={() => onSelect(key === selected ? null : key)}
                      title="Show this SKU's details"
                    >
                      <td>{c.sap_code}</td>
                      <td>{sku?.description ?? '—'}</td>
                      <td>{sku?.supplier ?? '—'}</td>
                      <td>{cityLabel(c.region)}</td>
                      <td className="num">{fmtQty(c.cartons)}</td>
                      <td>Week of {fmtDate(c.arrival_week)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          ) : (
            <p className="muted">This plan has no commits.</p>
          )}
          <button type="button" onClick={() => setLines(fromCommits(commits))}>
            {commits.length > 0 ? 'Edit commits' : 'Add commits'}
          </button>
        </>
      ) : (
        <>
          <CommitEditor lines={lines} onChange={setLines} skus={skus} weeks={weeks} disabled={saving} issue={issue} />
          <div className="commit-actions">
            <button type="button" className="primary" onClick={onSave} disabled={saving || issue !== null}>
              {saving ? 'Saving…' : 'Save commits'}
            </button>
            <button
              type="button"
              onClick={() => {
                setLines(null)
                setError(null)
              }}
              disabled={saving}
            >
              Cancel
            </button>
            <span className="muted">Saving recalculates this plan with the current principal settings.</span>
          </div>
          {error && (
            <div className="alert error" role="alert">
              {error}
            </div>
          )}
        </>
      )}
    </details>
  )
}
