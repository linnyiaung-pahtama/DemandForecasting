import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { errorText, exportUrl, getRun, recalculate } from '../api'
import FlagChips from '../components/FlagChips'
import SkuDetail from '../components/SkuDetail'
import { filterSkus, nextOrder } from '../lib/filters'
import type { SkuFilter } from '../lib/filters'
import { FLAG_LABELS, fmtDate, fmtQty } from '../lib/format'
import { useWeeksInput } from '../lib/useWeeksInput'
import type { FlagCode, RunRecord } from '../types'

const CARDS: { code: FlagCode; label: string }[] = [
  { code: 'ORDER_NOW', label: 'Order now' },
  { code: 'STOCKOUT_RISK', label: 'Stock-out risk' },
  { code: 'EXCESS', label: 'Excess stock' },
  { code: 'NO_FORECAST_HOLDING_STOCK', label: 'No forecast, holding stock' },
]

export default function PlanPage() {
  const { id } = useParams()
  const runId = Number(id)
  const [run, setRun] = useState<RunRecord | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [supplier, setSupplier] = useState<string | null>(null)
  const [flag, setFlag] = useState<FlagCode | null>(null)
  const [dueOn, setDueOn] = useState(true)
  const { weeks, inputProps: weeksInputProps } = useWeeksInput(4)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string | null>(null)

  // Id of the run currently shown; lets a slow recalculate response be ignored after navigation.
  const currentRunId = useRef(runId)

  useEffect(() => {
    let cancelled = false
    currentRunId.current = runId
    setRun(null)
    setError(null)
    setBusy(false)
    setSelected(null)
    setSupplier(null)
    setFlag(null)
    setSearch('')
    getRun(runId)
      .then((r) => {
        if (!cancelled) setRun(r)
      })
      .catch((err) => {
        if (!cancelled) setError(errorText(err))
      })
    return () => {
      cancelled = true
    }
  }, [runId])

  const result = run?.result
  const planDate = result?.plan_date ?? ''
  const windowWeeks = dueOn ? weeks : null

  const suppliers = useMemo(
    () => Array.from(new Set((result?.skus ?? []).map((s) => s.supplier))).sort((a, b) => a.localeCompare(b)),
    [result],
  )

  const rows = useMemo(() => {
    if (!result) return []
    const f: SkuFilter = { supplier, flag, dueWithinWeeks: windowWeeks, search }
    return filterSkus(result.skus, f, planDate)
  }, [result, supplier, flag, windowWeeks, search, planDate])

  const defaultCount = useMemo(
    () => (result?.settings_used ?? []).filter((s) => s.is_default).length,
    [result],
  )

  const selectedSku = useMemo(
    () => (result && selected ? (result.skus.find((s) => s.sap_code === selected) ?? null) : null),
    [result, selected],
  )

  async function onRecalculate() {
    setBusy(true)
    setError(null)
    try {
      const fresh = await recalculate(runId)
      if (currentRunId.current === runId) setRun(fresh)
    } catch (err) {
      if (currentRunId.current === runId) setError(errorText(err))
    } finally {
      if (currentRunId.current === runId) setBusy(false)
    }
  }

  function onCardClick(code: FlagCode) {
    if (flag === code) {
      setFlag(null)
    } else {
      setFlag(code)
      setDueOn(false) // count cards cover SKUs with no order due, so show them all
    }
  }

  if (!run || !result) {
    return error ? (
      <div className="alert error" role="alert">
        {error}
      </div>
    ) : (
      <p className="muted">Loading plan…</p>
    )
  }

  return (
    <div className="plan">
      <div className="plan-head">
        <div>
          <h2>Order plan</h2>
          <div className="muted">
            Plan date {fmtDate(result.plan_date)} · {run.file_name} · run {fmtDate(run.created_at)}
          </div>
        </div>
        <div className="plan-actions">
          <Link className="btn" to={`/runs/${runId}/suppliers`}>
            Supplier summary
          </Link>
          <button onClick={onRecalculate} disabled={busy}>
            {busy ? 'Recalculating…' : 'Recalculate with current settings'}
          </button>
          <a className="btn primary" href={exportUrl(runId, weeks)}>
            Export to Excel
          </a>
        </div>
      </div>

      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}

      {defaultCount > 0 && (
        <div className="alert warn">
          {defaultCount} suppliers are using default levels (20/30 days) —{' '}
          <Link to="/settings">review them in Supplier settings</Link>
        </div>
      )}

      <div className="cards">
        {CARDS.map((c) => (
          <button
            key={c.code}
            className={`count-card${flag === c.code ? ' active' : ''}`}
            onClick={() => onCardClick(c.code)}
            aria-pressed={flag === c.code}
          >
            <span className="count">{result.flag_counts[c.code] ?? 0}</span>
            <span>{c.label}</span>
          </button>
        ))}
      </div>

      <div className="filters">
        <label>
          Supplier{' '}
          <select value={supplier ?? ''} onChange={(e) => setSupplier(e.target.value || null)}>
            <option value="">All suppliers</option>
            {suppliers.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label>
          Flag{' '}
          <select value={flag ?? ''} onChange={(e) => setFlag((e.target.value || null) as FlagCode | null)}>
            <option value="">All flags</option>
            {(Object.keys(FLAG_LABELS) as FlagCode[]).map((code) => (
              <option key={code} value={code}>
                {FLAG_LABELS[code]}
              </option>
            ))}
          </select>
        </label>
        <label>
          <input type="checkbox" checked={dueOn} onChange={(e) => setDueOn(e.target.checked)} /> Orders due
          within{' '}
          <input
            type="number"
            min={1}
            max={52}
            {...weeksInputProps}
            style={{ width: '4.5rem' }}
          />{' '}
          weeks
        </label>
        <label>
          <input
            type="text"
            placeholder="Search SAP code or description"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <span className="muted">
          {rows.length} of {result.skus.length} SKUs
        </span>
      </div>

      <div className={`plan-body${selectedSku ? ' with-detail' : ''}`}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Supplier</th>
                <th>SAP Code</th>
                <th>Description</th>
                <th className="num">Sellable</th>
                <th className="num">SIT</th>
                <th className="num">Days of cover</th>
                <th>Next order date</th>
                <th className="num">Qty</th>
                <th>Arrival</th>
                <th>Flags</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => {
                const next = nextOrder(s)
                return (
                  <tr
                    key={s.sap_code}
                    className={`clickable${s.sap_code === selected ? ' selected' : ''}`}
                    onClick={() => setSelected(s.sap_code === selected ? null : s.sap_code)}
                  >
                    <td>{s.supplier}</td>
                    <td>{s.sap_code}</td>
                    <td>{s.description}</td>
                    <td className="num">{fmtQty(s.sellable)}</td>
                    <td className="num">{fmtQty(s.sit)}</td>
                    <td className="num">{s.days_of_cover === null ? '–' : fmtQty(s.days_of_cover)}</td>
                    <td>{next ? fmtDate(next.order_date) : '–'}</td>
                    <td className="num">{next ? fmtQty(next.qty) : '–'}</td>
                    <td>{next ? fmtDate(next.arrival_date) : '–'}</td>
                    <td>
                      <FlagChips flags={s.flags} />
                    </td>
                  </tr>
                )
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={10} className="muted">
                    No SKUs match the current filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          <p className="muted">Stock in transit is counted as available from the plan date.</p>
        </div>
        {selectedSku && <SkuDetail sku={selectedSku} onClose={() => setSelected(null)} />}
      </div>
    </div>
  )
}
