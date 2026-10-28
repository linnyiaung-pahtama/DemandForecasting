import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { errorText, getSettings, getSettingsLog, listRuns, recalculate, saveSettings } from '../api'
import { fmtDate, fmtMonths, fmtTime } from '../lib/format'
import { changedHoldings, validateHolding } from '../lib/settings'
import type { SettingsLogEntry, SupplierSettingView } from '../types'

interface Saved {
  runId: number
  file: string
}

function toDrafts(rows: SupplierSettingView[]): Record<string, string> {
  const drafts: Record<string, string> = {}
  for (const r of rows) drafts[r.supplier] = r.holding_months === null ? '' : fmtMonths(r.holding_months)
  return drafts
}

function holdingText(value: number | null): string {
  return value === null ? 'not set' : fmtMonths(value)
}

export default function SettingsPage() {
  const [rows, setRows] = useState<SupplierSettingView[] | null>(null)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<Saved | 'plain' | null>(null)
  const [log, setLog] = useState<SettingsLogEntry[] | null>(null)
  const [logError, setLogError] = useState<string | null>(null)

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
    getSettingsLog()
      .then((entries) => {
        if (!cancelled) setLog(entries)
      })
      .catch((err) => {
        if (!cancelled) setLogError(errorText(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Drafts stay as text so a half-typed value like "1." is not rewritten under the cursor.
  const checks = useMemo(() => {
    const out: Record<string, ReturnType<typeof validateHolding>> = {}
    for (const r of rows ?? []) out[r.supplier] = validateHolding(drafts[r.supplier] ?? '')
    return out
  }, [rows, drafts])

  const hasErrors = Object.values(checks).some((c) => c.error !== null)

  const changes = useMemo(() => {
    const edited: Record<string, number | null> = {}
    for (const r of rows ?? []) {
      const check = checks[r.supplier]
      if (check && check.error === null) edited[r.supplier] = check.value
    }
    return changedHoldings(rows ?? [], edited)
  }, [rows, checks])

  function edit(supplier: string, value: string) {
    setDrafts((prev) => ({ ...prev, [supplier]: value }))
    setSaved(null)
  }

  async function refreshLog() {
    try {
      setLog(await getSettingsLog())
      setLogError(null)
    } catch (err) {
      setLogError(errorText(err))
    }
  }

  async function onSave() {
    if (!rows || hasErrors || changes.length === 0) return
    setSaving(true)
    setSaveError(null)
    setSaved(null)
    try {
      const fresh = await saveSettings(changes)
      setRows(fresh)
      setDrafts(toDrafts(fresh))
      await refreshLog()
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
      // A 422 detail already names the supplier, so it is shown as is.
      setSaveError(errorText(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <h2>Supplier settings</h2>
      <p className="muted">
        Holding is how many months of stock to keep for each supplier. Order = average monthly demand × holding −
        (sellable + SIT). Lead time does not change the order quantity.
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
                  <th>Holding (months)</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const error = checks[r.supplier]?.error ?? null
                  return (
                    <tr key={r.supplier} className={r.holding_months === null ? 'default-row' : undefined}>
                      <td>{r.supplier}</td>
                      <td className="num">{r.sku_count}</td>
                      <td className="num">{r.max_lead_time_days ?? '–'}</td>
                      <td>
                        <input
                          type="text"
                          inputMode="decimal"
                          aria-label={`Holding months for ${r.supplier}`}
                          aria-invalid={error !== null}
                          value={drafts[r.supplier] ?? ''}
                          onChange={(e) => edit(r.supplier, e.target.value)}
                          style={{ width: '5.5rem' }}
                        />
                      </td>
                      <td>
                        {r.holding_months === null && <div className="note-default">Holding not set — SKUs blocked</div>}
                        {error && (
                          <div className="field-error" role="alert">
                            {error}
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <div className="save-bar">
            <button className="primary" onClick={onSave} disabled={hasErrors || saving || changes.length === 0}>
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

      <h2 className="section-head">Change log</h2>
      {logError && (
        <div className="alert error" role="alert">
          {logError}
        </div>
      )}
      {!log ? (
        !logError && <p className="muted">Loading change log…</p>
      ) : log.length === 0 ? (
        <p className="muted">No holding changes yet.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Supplier</th>
                <th className="num">From</th>
                <th className="num">To</th>
              </tr>
            </thead>
            <tbody>
              {log.map((e) => (
                <tr key={e.id}>
                  <td>
                    {fmtDate(e.changed_at)} {fmtTime(e.changed_at)}
                  </td>
                  <td>{e.supplier}</td>
                  <td className="num">{holdingText(e.old_value)}</td>
                  <td className="num">{holdingText(e.new_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
