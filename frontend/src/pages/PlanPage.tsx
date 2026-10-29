import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { errorText, exportUrl, getRun, recalculate } from '../api'
import SkuDetail from '../components/SkuDetail'
import StatusChip from '../components/StatusChip'
import WarningsPanel from '../components/WarningsPanel'
import { filterSkus } from '../lib/filters'
import type { SkuFilter } from '../lib/filters'
import { fmtCover, fmtDate, fmtMonths, fmtQty, hasMonthly, isLegacyRun, monthLabel, monthlyTotal, statusLabel } from '../lib/format'
import type { RunRecord, SkuStatus } from '../types'

const STATUSES: SkuStatus[] = ['TO_ORDER', 'NO_ORDER_NEEDED', 'HOLDING_NOT_SET', 'NO_DEMAND_DATA']

type Card = { key: string; label: string; status: SkuStatus } | { key: string; label: string; zero: true }

const CARDS: Card[] = [
  { key: 'TO_ORDER', label: 'To order', status: 'TO_ORDER' },
  { key: 'HOLDING_NOT_SET', label: 'Holding not set', status: 'HOLDING_NOT_SET' },
  { key: 'NO_DEMAND_DATA', label: 'No demand data', status: 'NO_DEMAND_DATA' },
  { key: 'ZERO_FORECAST', label: 'Zero forecast', zero: true },
]

// Keyed by run id so switching runs remounts the view: no stale run, filters or selection carry over.
export default function PlanPage() {
  const { id } = useParams()
  return <PlanView key={id} runId={Number(id)} />
}

function PlanView({ runId }: { runId: number }) {
  const [run, setRun] = useState<RunRecord | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [supplier, setSupplier] = useState<string | null>(null)
  const [status, setStatus] = useState<SkuStatus | null>(null)
  const [zeroForecastOnly, setZeroForecastOnly] = useState(false)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [view, setView] = useState<'cycle' | 'months'>('cycle')

  // Id of the run currently shown; lets a slow recalculate response be ignored after navigation.
  const currentRunId = useRef(runId)

  useEffect(() => {
    let cancelled = false
    currentRunId.current = runId
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

  const suppliers = useMemo(
    () => Array.from(new Set((result?.skus ?? []).map((s) => s.supplier))).sort((a, b) => a.localeCompare(b)),
    [result],
  )

  const rows = useMemo(() => {
    if (!result) return []
    const f: SkuFilter = { supplier, status, zeroForecastOnly, search }
    return filterSkus(result.skus, f)
  }, [result, supplier, status, zeroForecastOnly, search])

  const selectedSku = useMemo(
    () => (result && selected ? (result.skus.find((s) => s.sap_code === selected) ?? null) : null),
    [result, selected],
  )

  const selectedWarnings = useMemo(() => {
    if (!run || !selected) return []
    return [...run.parsed.warnings, ...run.actual.warnings, ...(run.stock?.warnings ?? [])].filter(
      (w) => w.sap_code === selected,
    )
  }, [run, selected])

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

  const filtersActive = supplier !== null || status !== null || zeroForecastOnly || search !== ''

  function clearFilters() {
    setSupplier(null)
    setStatus(null)
    setZeroForecastOnly(false)
    setSearch('')
  }

  function isActive(card: Card): boolean {
    return 'zero' in card ? zeroForecastOnly : status === card.status
  }

  function onCardClick(card: Card) {
    if ('zero' in card) setZeroForecastOnly(!zeroForecastOnly)
    else setStatus(status === card.status ? null : card.status)
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

  const blocked = result.blocked_suppliers.length

  return (
    <div className="plan">
      <div className="plan-head">
        <div>
          <h2>Order plan</h2>
          <div className="muted">Plan date {fmtDate(result.plan_date)}</div>
          <div className="muted">
            From {run.file_name} + {run.sales_file_name}
            {run.pg_file_name !== null && run.pdg_file_name !== null && ` + ${run.pg_file_name} + ${run.pdg_file_name}`}
          </div>
          {isLegacyRun(result) && (
            <div className="muted">
              Saved before MOQ and lead time moved to Supplier settings — Recalculate to use the current settings.
            </div>
          )}
        </div>
        <div className="plan-actions">
          <Link className="btn" to={`/runs/${runId}/suppliers`}>
            Supplier summary
          </Link>
          <button onClick={onRecalculate} disabled={busy}>
            {busy ? 'Recalculating…' : 'Recalculate'}
          </button>
          <a className="btn primary" href={exportUrl(runId)}>
            Export to Excel
          </a>
        </div>
      </div>

      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}

      {blocked > 0 && (
        <div className="alert warn">
          {blocked === 1 ? '1 supplier has no holding set, so its SKUs are' : `${blocked} suppliers have no holding set, so their SKUs are`}{' '}
          not calculated — set holding in <Link to="/settings">Supplier settings</Link>
        </div>
      )}

      <WarningsPanel
        dataWarnings={run.parsed.warnings}
        salesWarnings={run.actual.warnings}
        stockWarnings={run.stock?.warnings ?? []}
      />

      <div className="cards">
        {CARDS.map((c) => (
          <button
            key={c.key}
            className={`count-card${isActive(c) ? ' active' : ''}`}
            onClick={() => onCardClick(c)}
            aria-pressed={isActive(c)}
          >
            <span className="count">{result.counts[c.key] ?? 0}</span>
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
          Status{' '}
          <select value={status ?? ''} onChange={(e) => setStatus((e.target.value || null) as SkuStatus | null)}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {statusLabel(s)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={zeroForecastOnly}
            onChange={(e) => setZeroForecastOnly(e.target.checked)}
          />{' '}
          Zero forecast only
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
        {filtersActive && <button onClick={clearFilters}>Clear filters</button>}
      </div>

      <div className="view-switch" role="group" aria-label="Plan view">
        <button aria-pressed={view === 'cycle'} className={view === 'cycle' ? 'primary' : undefined} onClick={() => setView('cycle')}>
          This cycle
        </button>
        <button aria-pressed={view === 'months'} className={view === 'months' ? 'primary' : undefined} onClick={() => setView('months')}>
          12 months
        </button>
      </div>

      <div className={`plan-body${selectedSku ? ' with-detail' : ''}`}>
        <div className="table-wrap">
          {view === 'months' ? (
            hasMonthly(result) ? (
              <table className="plan-table">
                <thead>
                  <tr>
                    <th>Supplier</th>
                    <th>SAP Code</th>
                    <th>Description</th>
                    {result.plan_months.map((m) => (
                      <th key={m} className="num">
                        {monthLabel(m)}
                      </th>
                    ))}
                    <th className="num">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((s) => {
                    const total = monthlyTotal(s)
                    return (
                      <tr
                        key={s.sap_code}
                        className={`clickable${s.sap_code === selected ? ' selected' : ''}`}
                        onClick={() => setSelected(s.sap_code === selected ? null : s.sap_code)}
                      >
                        <td>{s.supplier}</td>
                        <td>{s.sap_code}</td>
                        <td>{s.description}</td>
                        {(s.monthly ?? []).map((m) => (
                          <OrderCell key={m.month} qty={m.order} moqApplied={m.moq_applied} />
                        ))}
                        <td className="num">{total === null ? '—' : fmtQty(total)}</td>
                      </tr>
                    )
                  })}
                  {rows.length === 0 && (
                    <tr>
                      <td colSpan={result.plan_months.length + 4} className="muted">
                        No SKUs match the current filters.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            ) : (
              <p className="muted">Recalculate to see the 12-month plan.</p>
            )
          ) : (
            <>
            <table className="plan-table">
              <thead>
                <tr>
                  <th>Supplier</th>
                  <th>SAP Code</th>
                  <th>Description</th>
                  <th className="num">Available</th>
                  <th className="num">Buffer</th>
                  <th className="num">Valid</th>
                  <th className="num">Holding</th>
                  <th className="num">Target</th>
                  <th className="num">Order qty</th>
                  <th className="num">Stock cover</th>
                  <th>Next calc date</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr
                    key={s.sap_code}
                    className={`clickable${s.sap_code === selected ? ' selected' : ''}`}
                    onClick={() => setSelected(s.sap_code === selected ? null : s.sap_code)}
                  >
                    <td>{s.supplier}</td>
                    <td>{s.sap_code}</td>
                    <td>{s.description}</td>
                    <td className="num">{fmtQty(s.available)}</td>
                    <td className="num">{s.buffer === null ? '—' : fmtQty(s.buffer)}</td>
                    <td className="num">
                      {s.valid_count}/{s.demand_values.length}
                    </td>
                    <td className="num">{s.holding_months === null ? '—' : fmtMonths(s.holding_months)}</td>
                    <td className="num">{s.target === null ? '—' : fmtQty(s.target)}</td>
                    <OrderCell qty={s.order_qty} moqApplied={s.moq_applied} />
                    <td className="num">{s.stock_cover_months === null ? '—' : `${fmtCover(s.stock_cover_months)} mo`}</td>
                    <td>{s.next_calc_date === null ? '—' : fmtDate(s.next_calc_date)}</td>
                    <td>
                      <StatusChip status={s.status} zeroForecast={s.zero_forecast} />
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={12} className="muted">
                      No SKUs match the current filters.{' '}
                      {filtersActive && (
                        <button className="link-button" onClick={clearFilters}>
                          Clear filters
                        </button>
                      )}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            <p className="muted">
              Buffer is the average of the valid monthly values; order qty brings stock (sellable plus SIT) up to
              buffer × holding. Click a row to see the arithmetic.
            </p>
            </>
          )}
        </div>
        {selectedSku && (
          <SkuDetail
            sku={selectedSku}
            planDate={result.plan_date}
            warnings={selectedWarnings}
            onClose={() => setSelected(null)}
          />
        )}
      </div>
    </div>
  )
}

/** An order quantity cell: quantities above zero get the turmeric tag so what needs buying stands out. */
function OrderCell({ qty, moqApplied }: { qty: number | null; moqApplied: boolean }) {
  return (
    <td className={`num${qty !== null && qty > 0 ? ' order-qty' : ''}`}>
      {qty === null ? '—' : qty > 0 ? <span className="qty">{fmtQty(qty)}</span> : fmtQty(qty)}
      {moqApplied && <span className="chip chip-grey tag">MOQ</span>}
    </td>
  )
}