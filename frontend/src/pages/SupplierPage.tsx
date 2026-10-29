import { Fragment, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { errorText, getRun, getSupplierSummary } from '../api'
import { fmtDate, fmtMonths, fmtQty, monthLabel } from '../lib/format'
import type { RunRecord, SkuResult, SupplierSummary } from '../types'

const COLUMNS = 10

// Keyed by run id so switching runs remounts the view: no stale run or expanded rows carry over.
export default function SupplierPage() {
  const { id } = useParams()
  return <SupplierView key={id} runId={Number(id)} />
}

function SupplierView({ runId }: { runId: number }) {
  const [run, setRun] = useState<RunRecord | null>(null)
  const [summary, setSummary] = useState<SupplierSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  // One load for both, so the page shows a single "Loading…" state.
  useEffect(() => {
    let cancelled = false
    Promise.all([getRun(runId), getSupplierSummary(runId)])
      .then(([r, rows]) => {
        if (cancelled) return
        setRun(r)
        setSummary(rows)
      })
      .catch((err) => {
        if (!cancelled) setError(errorText(err))
      })
    return () => {
      cancelled = true
    }
  }, [runId])

  // SKUs to order, grouped by supplier: the lines for one purchase order.
  const linesBySupplier = useMemo(() => {
    const map = new Map<string, SkuResult[]>()
    for (const sku of run?.result.skus ?? []) {
      if ((sku.order_qty ?? 0) <= 0) continue
      const lines = map.get(sku.supplier) ?? []
      lines.push(sku)
      map.set(sku.supplier, lines)
    }
    for (const lines of map.values()) {
      lines.sort((a, b) => a.description.localeCompare(b.description) || a.sap_code.localeCompare(b.sap_code))
    }
    return map
  }, [run])

  function toggle(supplier: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(supplier)) next.delete(supplier)
      else next.add(supplier)
      return next
    })
  }

  return (
    <div>
      <div className="plan-head">
        <div>
          <h2>Principal summary</h2>
          {run && (
            <>
              <div className="muted">Plan date {fmtDate(run.result.plan_date)}</div>
              <div className="muted">
                From {run.file_name} + {run.sales_file_name}
              </div>
            </>
          )}
        </div>
        <div className="plan-actions">
          <Link className="btn" to={`/runs/${runId}`}>
            Back to order plan
          </Link>
        </div>
      </div>

      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}

      {!summary || !run ? (
        !error && <p className="muted">Loading…</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Principal</th>
                <th className="num">Holding (months)</th>
                <th className="num">MOQ</th>
                <th className="num">Lead time (days)</th>
                <th className="num">SKUs</th>
                <th className="num">SKUs to order</th>
                <th className="num">Total order qty</th>
                <th className="num">Blocked</th>
                <th className="num">No demand</th>
                <th className="num">Zero forecast</th>
              </tr>
            </thead>
            <tbody>
              {summary.map((s) => {
                const open = expanded.has(s.supplier)
                const lines = linesBySupplier.get(s.supplier) ?? []
                return (
                  <Fragment key={s.supplier}>
                    <tr className="clickable" onClick={() => toggle(s.supplier)}>
                      <td>
                        <button
                          type="button"
                          className="link-button"
                          aria-expanded={open}
                          onClick={(e) => {
                            e.stopPropagation()
                            toggle(s.supplier)
                          }}
                        >
                          {open ? '▾' : '▸'} {s.supplier}
                        </button>
                      </td>
                      <td className="num">
                        {s.holding_months === null ? (
                          <span className="chip chip-red">not set</span>
                        ) : (
                          fmtMonths(s.holding_months)
                        )}
                      </td>
                      <td className="num">{s.moq === null ? '—' : fmtQty(s.moq)}</td>
                      <td className="num">{s.lead_time_days ?? '—'}</td>
                      <td className="num">{s.sku_count}</td>
                      <td className="num">{s.skus_to_order}</td>
                      <td className="num">{fmtQty(s.total_order_qty)}</td>
                      <td className="num">{s.blocked_skus}</td>
                      <td className="num">{s.no_demand_skus}</td>
                      <td className="num">{s.zero_forecast_skus}</td>
                    </tr>
                    {open && (
                      <tr className="expanded-row">
                        <td colSpan={COLUMNS}>
                          {lines.length === 0 ? (
                            <span className="muted">
                              {s.holding_months === null
                                ? 'Holding not set, so no orders are calculated for this principal.'
                                : 'No SKUs to order.'}
                            </span>
                          ) : (
                            <table className="inner">
                              <thead>
                                <tr>
                                  <th>SAP Code</th>
                                  <th>Description</th>
                                  <th className="num">Order qty</th>
                                  <th>Next calc date</th>
                                </tr>
                              </thead>
                              <tbody>
                                {lines.map((sku) => (
                                  <tr key={sku.sap_code}>
                                    <td>{sku.sap_code}</td>
                                    <td>{sku.description}</td>
                                    <td className="num">
                                      {fmtQty(sku.order_qty ?? 0)}
                                      {sku.moq_applied && <span className="chip chip-grey tag">MOQ</span>}
                                    </td>
                                    <td>{sku.next_calc_date === null ? '—' : fmtDate(sku.next_calc_date)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
              {summary.length === 0 && (
                <tr>
                  <td colSpan={COLUMNS} className="muted">
                    This run has no principals.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          <p className="muted">Expand a principal to see the SKUs on its purchase order.</p>

          <h2 className="section-head">12-month order demand forecast</h2>
          {run.result.plan_months.length === 0 ? (
            <p className="muted">Recalculate to see the 12-month plan.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Principal</th>
                  {run.result.plan_months.map((m) => (
                    <th key={m} className="num">
                      {monthLabel(m)}
                    </th>
                  ))}
                  <th className="num">Total</th>
                </tr>
              </thead>
              <tbody>
                {summary.map((s) => (
                  <tr key={s.supplier}>
                    <td>{s.supplier}</td>
                    {/* null when the supplier's holding is not set: nothing was calculated, so "—" rather than 0 */}
                    {run.result.plan_months.map((m, i) => (
                      <td key={m} className="num">
                        {s.monthly_order_qty === null ? '—' : fmtQty(s.monthly_order_qty[i])}
                      </td>
                    ))}
                    <td className="num">{s.twelve_month_total === null ? '—' : fmtQty(s.twelve_month_total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
