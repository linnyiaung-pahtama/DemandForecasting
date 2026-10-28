import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createRun, errorText, inspectFiles } from '../api'
import { fmtDate, monthLabel } from '../lib/format'
import type { InspectResponse } from '../types'

function monthRange(months: string[]): string {
  if (months.length === 0) return 'none'
  if (months.length === 1) return monthLabel(months[0])
  return `${monthLabel(months[0])} – ${monthLabel(months[months.length - 1])}`
}

export default function UploadPage() {
  const navigate = useNavigate()
  const [dataFile, setDataFile] = useState<File | null>(null)
  const [salesFile, setSalesFile] = useState<File | null>(null)
  const [info, setInfo] = useState<InspectResponse | null>(null)
  const [planDate, setPlanDate] = useState('')
  const [inspecting, setInspecting] = useState(false)
  const [calculating, setCalculating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Inspect whenever both files are chosen or either changes. The cleanup flag drops a
  // response that arrives after the files have changed again.
  useEffect(() => {
    setInfo(null)
    setError(null)
    if (!dataFile || !salesFile) {
      setInspecting(false)
      return
    }
    let current = true
    setInspecting(true)
    inspectFiles(dataFile, salesFile)
      .then((result) => {
        if (!current) return
        setInfo(result)
        setPlanDate(result.default_plan_date)
        setInspecting(false)
      })
      .catch((err) => {
        if (!current) return
        setError(errorText(err))
        setInspecting(false)
      })
    return () => {
      current = false
    }
  }, [dataFile, salesFile])

  async function onCalculate() {
    if (!dataFile || !salesFile || !info) return
    setCalculating(true)
    setError(null)
    try {
      const run = await createRun(dataFile, salesFile, planDate || undefined)
      navigate(`/runs/${run.id}`)
    } catch (err) {
      setError(errorText(err))
      setCalculating(false)
    }
  }

  return (
    <div className="stack">
      <div className="card">
        <h2>New plan</h2>
        <p className="muted">
          Choose the planner's Excel forecast file (only the Data sheet is read) and the sales export.
        </p>
        <div className="field">
          <label htmlFor="data-file">Data file (.xlsx)</label>
          <input
            id="data-file"
            type="file"
            accept=".xlsx"
            onChange={(e) => setDataFile(e.target.files?.[0] ?? null)}
            disabled={calculating}
          />
        </div>
        <div className="field">
          <label htmlFor="sales-file">Sales export (.xlsx)</label>
          <input
            id="sales-file"
            type="file"
            accept=".xlsx"
            onChange={(e) => setSalesFile(e.target.files?.[0] ?? null)}
            disabled={calculating}
          />
        </div>
        {inspecting && <p className="muted">Reading files…</p>}
      </div>

      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}

      {info && (
        <div className="card">
          <h2>
            {info.file_name} + {info.sales_file_name}
          </h2>
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
              <dt>Actual months</dt>
              <dd>{monthRange(info.actual_months)}</dd>
            </div>
            <div>
              <dt>Forecast months</dt>
              <dd>{monthRange(info.forecast_window)}</dd>
            </div>
          </dl>
          <p>
            {info.skus_with_sales} of {info.sku_count} SKUs have actual sales
          </p>

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
            <span className="muted">
              Stock figures are as of {fmtDate(info.mtd_end)}; the plan date can be up to the end of that
              month.
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
