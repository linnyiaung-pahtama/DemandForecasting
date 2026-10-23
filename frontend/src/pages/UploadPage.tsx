import { useState } from 'react'
import type { ChangeEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, createRun, inspectFile } from '../api'
import { fmtDate } from '../lib/format'
import type { InspectResponse } from '../types'

function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  return err instanceof Error ? err.message : String(err)
}

export default function UploadPage() {
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [info, setInfo] = useState<InspectResponse | null>(null)
  const [planDate, setPlanDate] = useState('')
  const [inspecting, setInspecting] = useState(false)
  const [calculating, setCalculating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function onFileChange(e: ChangeEvent<HTMLInputElement>) {
    const chosen = e.target.files?.[0] ?? null
    setFile(chosen)
    setInfo(null)
    setError(null)
    if (!chosen) return
    setInspecting(true)
    try {
      const result = await inspectFile(chosen)
      setInfo(result)
      setPlanDate(result.default_plan_date)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setInspecting(false)
    }
  }

  async function onCalculate() {
    if (!file || !info) return
    setCalculating(true)
    setError(null)
    try {
      const run = await createRun(file, planDate || undefined)
      navigate(`/runs/${run.id}`)
    } catch (err) {
      setError(errorText(err))
      setCalculating(false)
    }
  }

  const months = info?.forecast_months ?? []
  const monthRange =
    months.length === 0
      ? 'none'
      : months.length === 1
        ? months[0]
        : `${months[0]} to ${months[months.length - 1]} (${months.length} months)`

  return (
    <div className="stack">
      <div className="card">
        <h2>New plan</h2>
        <p className="muted">Choose the planner's Excel forecast file (.xlsx). Only the Data sheet is read.</p>
        <input type="file" accept=".xlsx" onChange={onFileChange} disabled={calculating} />
        {inspecting && <p className="muted">Reading file…</p>}
      </div>

      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}

      {info && (
        <div className="card">
          <h2>{info.file_name}</h2>
          <dl className="facts">
            <div>
              <dt>SKUs</dt>
              <dd>{info.sku_count}</dd>
            </div>
            <div>
              <dt>Suppliers</dt>
              <dd>{info.supplier_count}</dd>
            </div>
            <div>
              <dt>MTD column</dt>
              <dd>{info.mtd_label}</dd>
            </div>
            <div>
              <dt>Forecast months</dt>
              <dd>{monthRange}</dd>
            </div>
          </dl>

          <div className="field">
            <label htmlFor="plan-date">Plan date</label>
            <input
              id="plan-date"
              type="date"
              value={planDate}
              min={info.min_plan_date}
              max={info.max_plan_date}
              onChange={(e) => setPlanDate(e.target.value)}
            />
            <span className="muted">
              Detected {fmtDate(info.default_plan_date)}. Allowed {fmtDate(info.min_plan_date)} to{' '}
              {fmtDate(info.max_plan_date)}.
            </span>
          </div>

          <details className="warnings">
            <summary>
              Warnings <span className="badge">{info.warnings.length}</span>
            </summary>
            {info.warnings.length === 0 ? (
              <p className="muted">No warnings.</p>
            ) : (
              <ul>
                {info.warnings.map((w, i) => (
                  <li key={i}>
                    {(w.sap_code || w.column) && (
                      <strong>{[w.sap_code, w.column].filter(Boolean).join(' / ')}: </strong>
                    )}
                    {w.message}
                  </li>
                ))}
              </ul>
            )}
          </details>

          <button className="primary" onClick={onCalculate} disabled={calculating || !planDate}>
            {calculating ? 'Calculating…' : 'Calculate'}
          </button>
        </div>
      )}
    </div>
  )
}
