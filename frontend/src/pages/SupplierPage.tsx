import { Fragment, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { errorText, getRun, getSupplierSummary } from '../api'
import ModeSwitch from '../components/ModeSwitch'
import { cityLabel, fmtDate, fmtQty, monthLabel } from '../lib/format'
import { hasOrderPlan, MODE_LABEL, modeQuery, poLines, rowKey, skuView, summaryView } from '../lib/mode'
import { usePlanMode } from '../lib/usePlanMode'
import type { RunRecord, SupplierSummary } from '../types'

const COLUMNS = 11

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
  const [mode, setMode] = usePlanMode()

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

  // An older run has no order plan: in plan mode its order figures are blank and the page asks for a recalculation.
  const noPlan = run !== null && mode === 'plan' && !hasOrderPlan(run.result)

  // SKUs to order this month in the chosen mode, grouped by principal: the lines for one purchase order.
  const linesBySupplier = useMemo(() => poLines(run?.result.skus ?? [], mode), [run, mode])
  // A run split by city lists each line's city; older runs have one combined line per SKU.
  const byCity = useMemo(() => (run?.result.skus ?? []).some((s) => s.city !== null), [run])

  // Largest purchase order first in the chosen mode, then by name.
  const rows = useMemo(
    () =>
      [...(summary ?? [])].sort(
        (a, b) =>
          (summaryView(b, mode).totalOrderQty ?? 0) - (summaryView(a, mode).totalOrderQty ?? 0) ||
          a.supplier.localeCompare(b.supplier),
      ),
    [summary, mode],
  )

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
          <Link className="btn" to={`/runs/${runId}${modeQuery(mode)}`}>
            Back to order plan
          </Link>
        </div>
      </div>

      <ModeSwitch mode={mode} onChange={setMode} />

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
                <th className="num">Holding (days)</th>
                <th className="num">MOQ</th>
                <th className="num">Lead time (days)</th>
                <th className="num">Order cycle (weeks)</th>
                <th className="num">SKUs</th>
                <th className="num">SKUs to order</th>
                <th className="num">Total order qty</th>
                <th className="num">Blocked</th>
                <th className="num">No demand</th>
                <th className="num">Zero forecast</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => {
                const open = expanded.has(s.supplier)
                const lines = linesBySupplier.get(s.supplier) ?? []
                const view = summaryView(s, mode)
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
                        {s.holding_days === null ? (
                          <span className="chip chip-red">not set</span>
                        ) : (
                          fmtQty(s.holding_days)
                        )}
                      </td>
                      <td className="num">{s.moq === null ? '—' : fmtQty(s.moq)}</td>
                      <td className="num">{s.lead_time_days ?? '—'}</td>
                      <td className="num">{s.order_cycle_weeks ?? '—'}</td>
                      <td className="num">{s.sku_count}</td>
                      <td className="num">{view.skusToOrder ?? '—'}</td>
                      <td className="num">{view.totalOrderQty === null ? '—' : fmtQty(view.totalOrderQty)}</td>
                      <td className="num">{s.blocked_skus}</td>
                      <td className="num">{s.no_demand_skus}</td>
                      <td className="num">{s.zero_forecast_skus}</td>
                    </tr>
                    {open && (
                      <tr className="expanded-row">
                        <td colSpan={COLUMNS}>
                          {noPlan ? (
                            <span className="muted">Recalculate to see the order plan.</span>
                          ) : lines.length === 0 ? (
                            <span className="muted">
                              {s.holding_days === null
                                ? 'Holding not set, so no orders are calculated for this principal.'
                                : 'No SKUs to order.'}
                            </span>
                          ) : (
                            <table className="inner">
                              <thead>
                                <tr>
                                  <th>SAP Code</th>
                                  <th>Description</th>
                                  {byCity && <th>Region</th>}
                                  <th className="num">Order qty</th>
                                  <th>Next calc date</th>
                                </tr>
                              </thead>
                              <tbody>
                                {lines.map((sku) => {
                                  const line = skuView(sku, mode)
                                  return (
                                    <tr key={rowKey(sku)}>
                                      <td>{sku.sap_code}</td>
                                      <td>{sku.description}</td>
                                      {byCity && <td>{cityLabel(sku.city)}</td>}
                                      <td className="num">
                                        {fmtQty(line.orderQty ?? 0)}
                                        {line.moqApplied && <span className="chip chip-grey tag">MOQ</span>}
                                      </td>
                                      <td>{sku.next_calc_date === null ? '—' : fmtDate(sku.next_calc_date)}</td>
                                    </tr>
                                  )
                                })}
                              </tbody>
                            </table>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={COLUMNS} className="muted">
                    This run has no principals.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          <p className="muted">Expand a principal to see the SKUs on this month&apos;s purchase order.</p>

          <h2 className="section-head">12-month {MODE_LABEL[mode].toLowerCase()}</h2>
          {run.result.plan_months.length === 0 || noPlan ? (
            <p className="muted">
              {run.result.plan_months.length === 0
                ? 'Recalculate to see the 12-month plan.'
                : 'Recalculate to see the order plan.'}
            </p>
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
                {rows.map((s) => {
                  const view = summaryView(s, mode)
                  return (
                    <tr key={s.supplier}>
                      <td>{s.supplier}</td>
                      {/* "—" when the principal's holding is not set (nothing calculated); "·" between order months */}
                      {run.result.plan_months.map((m, i) => {
                        const qty = view.monthly === null ? undefined : view.monthly[i]
                        return (
                          <td
                            key={m}
                            className={`num${qty === null ? ' not-order' : ''}`}
                            title={qty === null ? 'Not an order month' : undefined}
                          >
                            {qty === undefined ? '—' : qty === null ? '·' : fmtQty(qty)}
                          </td>
                        )
                      })}
                      <td className="num">{view.twelveMonthTotal === null ? '—' : fmtQty(view.twelveMonthTotal)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
