import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { errorText, getSettings, listRuns, recalculate, saveSettings } from '../api'
import { changedSettings, validateSetting } from '../lib/settings'
import type { SupplierSettingView } from '../types'

interface Draft {
  reorder: string
  target: string
}

interface Saved {
  runId: number
  file: string
}

function toDrafts(rows: SupplierSettingView[]): Record<string, Draft> {
  const drafts: Record<string, Draft> = {}
  for (const r of rows) drafts[r.supplier] = { reorder: String(r.reorder_days), target: String(r.target_days) }
  return drafts
}

export default function SettingsPage() {
  const [rows, setRows] = useState<SupplierSettingView[] | null>(null)
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<Saved | 'plain' | null>(null)

  useEffect(() => {
    let cancelled = false
    getSettings()
      .then((r) => {
        if (cancelled) return
        setRows(r)
        setDrafts(toDrafts(r))
      })
      .catch((err) => {
        if (!cancelled) setLoadError(errorText(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Number('') is 0 and Number('abc') is NaN, so blank or non-numeric input fails validation.
  const checks = useMemo(() => {
    const out: Record<string, ReturnType<typeof validateSetting>> = {}
    for (const r of rows ?? []) {
      const d = drafts[r.supplier]
      if (!d) continue
      out[r.supplier] = validateSetting(
        { reorder_days: Number(d.reorder), target_days: Number(d.target) },
        r.max_lead_time_days,
      )
    }
    return out
  }, [rows, drafts])

  const hasErrors = Object.values(checks).some((c) => c.errors.length > 0)

  // Only rows the planner changed are saved, so untouched defaults stay flagged as unreviewed.
  const changes = useMemo(
    () =>
      changedSettings(
        rows ?? [],
        (rows ?? []).map((r) => ({
          supplier: r.supplier,
          reorder_days: Number(drafts[r.supplier]?.reorder ?? r.reorder_days),
          target_days: Number(drafts[r.supplier]?.target ?? r.target_days),
        })),
      ),
    [rows, drafts],
  )

  function edit(supplier: string, field: keyof Draft, value: string) {
    setDrafts((prev) => ({ ...prev, [supplier]: { ...prev[supplier], [field]: value } }))
    setSaved(null)
  }

  async function onSave() {
    if (!rows || changes.length === 0) return
    setSaving(true)
    setSaveError(null)
    setSaved(null)
    try {
      const fresh = await saveSettings(changes)
      setRows(fresh)
      setDrafts(toDrafts(fresh))
      let latest
      try {
        const runs = await listRuns()
        latest = runs.reduce((a, b) => (b.id > a.id ? b : a), runs[0])
      } catch (err) {
        setSaveError(`Saved, but could not look up the latest plan to recalculate: ${errorText(err)}`)
        return
      }
      if (!latest) {
        setSaved('plain')
        return
      }
      try {
        await recalculate(latest.id)
        setSaved({ runId: latest.id, file: latest.file_name })
      } catch (err) {
        setSaveError(`Saved, but recalculating the plan for ${latest.file_name} failed: ${errorText(err)}`)
      }
    } catch (err) {
      setSaveError(errorText(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <h2>Supplier settings</h2>
      <p className="muted">
        Reorder and target levels are in days of sales and include lead time. When stock plus orders on the way
        drops below the reorder level, an order brings it back up to the target level.
      </p>

      {loadError && (
        <div className="alert error" role="alert">
          {loadError}
        </div>
      )}

      {!rows ? (
        !loadError && <p className="muted">Loading settings…</p>
      ) : rows.length === 0 ? (
        <p className="muted">
          No suppliers yet. They appear here after you <Link to="/">upload a forecast</Link>.
        </p>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Supplier</th>
                  <th className="num">SKUs</th>
                  <th className="num">Max lead time (days)</th>
                  <th>Reorder days</th>
                  <th>Target days</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const d = drafts[r.supplier]
                  const check = checks[r.supplier] ?? { errors: [], warnings: [] }
                  return (
                    <tr key={r.supplier} className={r.is_default ? 'default-row' : undefined}>
                      <td>{r.supplier}</td>
                      <td className="num">{r.sku_count}</td>
                      <td className="num">{r.max_lead_time_days ?? '–'}</td>
                      <td>
                        <input
                          type="number"
                          min={1}
                          max={365}
                          step={1}
                          aria-label={`Reorder days for ${r.supplier}`}
                          value={d?.reorder ?? ''}
                          onChange={(e) => edit(r.supplier, 'reorder', e.target.value)}
                          style={{ width: '5.5rem' }}
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min={1}
                          max={365}
                          step={1}
                          aria-label={`Target days for ${r.supplier}`}
                          value={d?.target ?? ''}
                          onChange={(e) => edit(r.supplier, 'target', e.target.value)}
                          style={{ width: '5.5rem' }}
                        />
                      </td>
                      <td>
                        {r.is_default && <div className="note-default">Using default — please review</div>}
                        {check.errors.map((m) => (
                          <div key={m} className="field-error" role="alert">
                            {m}
                          </div>
                        ))}
                        {check.warnings.map((m) => (
                          <div key={m} className="field-warning">
                            {m}
                          </div>
                        ))}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <div className="save-bar">
            <button
              className="primary"
              onClick={onSave}
              disabled={hasErrors || saving || changes.length === 0}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
            {hasErrors ? (
              <span className="muted">Fix the errors above to save.</span>
            ) : (
              changes.length === 0 && !saving && <span className="muted">No changes to save.</span>
            )}
          </div>
        </>
      )}

      {saveError && (
        <div className="alert error" role="alert">
          {saveError}
        </div>
      )}
      {saved === 'plain' && <div className="alert ok">Saved.</div>}
      {saved && saved !== 'plain' && (
        <div className="alert ok">
          Saved. Plan for {saved.file} recalculated. <Link to={`/runs/${saved.runId}`}>Open the plan</Link>
        </div>
      )}
    </div>
  )
}
