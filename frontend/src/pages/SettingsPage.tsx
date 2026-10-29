import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { errorText, getSettings, getSettingsLog, listRuns, recalculate, saveSettings } from '../api'
import { fmtDate, fmtMonths, fmtTime } from '../lib/format'
import {
  changedSettings,
  logValue,
  validateHolding,
  validateLeadTime,
  validateMoq,
  type EditedSettings,
  type Parsed,
} from '../lib/settings'
import type { SettingField, SettingsLogEntry, SupplierSettingView } from '../types'

interface Saved {
  runId: number
  file: string
}

interface Draft {
  holding: string
  moq: string
  lead: string
}

interface Checks {
  holding: Parsed
  moq: Parsed
  lead: Parsed
}

function toDrafts(rows: SupplierSettingView[]): Record<string, Draft> {
  const drafts: Record<string, Draft> = {}
  for (const r of rows) {
    drafts[r.supplier] = {
      holding: r.holding_months === null ? '' : fmtMonths(r.holding_months),
      moq: String(r.moq),
      lead: r.lead_time_days === null ? '' : String(r.lead_time_days),
    }
  }
  return drafts
}

const FIELD_LABEL: Record<SettingField, string> = { holding_months: 'Holding', moq: 'MOQ', lead_time_days: 'Lead time' }

const EMPTY: Draft = { holding: '', moq: '', lead: '' }

export default function SettingsPage() {
  const [rows, setRows] = useState<SupplierSettingView[] | null>(null)
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
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
    const out: Record<string, Checks> = {}
    for (const r of rows ?? []) {
      const d = drafts[r.supplier] ?? EMPTY
      out[r.supplier] = { holding: validateHolding(d.holding), moq: validateMoq(d.moq), lead: validateLeadTime(d.lead) }
    }
    return out
  }, [rows, drafts])

  const hasErrors = Object.values(checks).some((c) => c.holding.error || c.moq.error || c.lead.error)

  const changes = useMemo(() => {
    const edited: Record<string, EditedSettings> = {}
    for (const r of rows ?? []) {
      const c = checks[r.supplier]
      if (c && !c.holding.error && !c.moq.error && !c.lead.error && c.moq.value !== null) {
        edited[r.supplier] = { holding_months: c.holding.value, moq: c.moq.value, lead_time_days: c.lead.value }
      }
    }
    return changedSettings(rows ?? [], edited)
  }, [rows, checks])

  function edit(supplier: string, field: keyof Draft, value: string) {
    setDrafts((prev) => ({ ...prev, [supplier]: { ...(prev[supplier] ?? EMPTY), [field]: value } }))
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
        (sellable + SIT). An order above 0 but below the supplier's MOQ is raised to the MOQ; the MOQ applies to each
        SKU of the supplier on its own (0 = no minimum). Lead time only sets the next calculation date.
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
                  <th>Holding (months)</th>
                  <th>MOQ (cartons)</th>
                  <th>Lead time (days)</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const c = checks[r.supplier]
                  const d = drafts[r.supplier] ?? EMPTY
                  const errors = c ? [c.holding.error, c.moq.error, c.lead.error].filter((e): e is string => e !== null) : []
                  return (
                    <tr key={r.supplier} className={r.holding_months === null ? 'default-row' : undefined}>
                      <td>{r.supplier}</td>
                      <td className="num">{r.sku_count}</td>
                      <td>
                        <input
                          type="text"
                          inputMode="decimal"
                          aria-label={`Holding months for ${r.supplier}`}
                          aria-invalid={Boolean(c?.holding.error)}
                          value={d.holding}
                          onChange={(e) => edit(r.supplier, 'holding', e.target.value)}
                          style={{ width: '5.5rem' }}
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          inputMode="numeric"
                          aria-label={`MOQ for ${r.supplier}`}
                          aria-invalid={Boolean(c?.moq.error)}
                          value={d.moq}
                          onChange={(e) => edit(r.supplier, 'moq', e.target.value)}
                          style={{ width: '6.5rem' }}
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          inputMode="numeric"
                          aria-label={`Lead time days for ${r.supplier}`}
                          aria-invalid={Boolean(c?.lead.error)}
                          value={d.lead}
                          onChange={(e) => edit(r.supplier, 'lead', e.target.value)}
                          style={{ width: '4.5rem' }}
                        />
                      </td>
                      <td>
                        {r.holding_months === null && <div className="note-default">Holding not set — SKUs blocked</div>}
                        {r.lead_time_days === null && (
                          <div className="muted">Lead time not set — no next calculation date</div>
                        )}
                        {errors.map((e) => (
                          <div key={e} className="field-error" role="alert">
                            {e}
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
        <p className="muted">No setting changes yet.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Supplier</th>
                <th>Setting</th>
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
                  <td>{FIELD_LABEL[e.field]}</td>
                  <td className="num">{logValue(e.field, e.old_value)}</td>
                  <td className="num">{logValue(e.field, e.new_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
