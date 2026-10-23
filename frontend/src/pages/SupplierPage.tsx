import { Fragment, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { errorText, getRun, getSupplierSummary } from '../api'
import { ordersInWindow } from '../lib/filters'
import { FLAG_LABELS, flagTone, fmtDate, fmtQty } from '../lib/format'
import { useWeeksInput } from '../lib/useWeeksInput'
import type { FlagCode, PlannedOrder, RunRecord, SkuPlan, SupplierSummary } from '../types'

const FLAG_CODES = Object.keys(FLAG_LABELS) as FlagCode[]

interface OrderLine {
  sku: SkuPlan
  order: PlannedOrder
}

export default function SupplierPage() {
  const { id } = useParams()
  const runId = Number(id)
  const { weeks, inputProps: weeksInputProps } = useWeeksInput(4)
  const [run, setRun] = useState<RunRecord | null>(null)
  const [summary, setSummary] = useState<SupplierSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  useEffect(() => {
    let cancelled = false
    setRun(null)
    setExpanded(new Set())
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

  useEffect(() => {
    let cancelled = false
    setSummary(null)
    setError(null)
    getSupplierSummary(runId, weeks)
      .then((rows) => {
        if (!cancelled) setSummary(rows)
      })
      .catch((err) => {
        if (!cancelled) setError(errorText(err))
      })
    return () => {
      cancelled = true
    }
  }, [runId, weeks])

  const planDate = run?.result.plan_date ?? ''

  // Orders inside the window, grouped by supplier, earliest first: the lines for one purchase order.
  const linesBySupplier = useMemo(() => {
    const map = new Map<string, OrderLine[]>()
    for (const sku of run?.result.skus ?? []) {
      for (const order of ordersInWindow(sku, planDate, weeks)) {
        const lines = map.get(sku.supplier) ?? []
        lines.push({ sku, order })
        map.set(sku.supplier, lines)
      }
    }
    for (const lines of map.values()) {
      lines.sort(
        (a, b) =>
          a.order.order_date.localeCompare(b.order.order_date) ||
          a.sku.description.localeCompare(b.sku.description),
      )
    }
    return map
  }, [run, planDate, weeks])

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
          <h2>Supplier summary</h2>
          {run && (
            <div className="muted">
              Plan date {fmtDate(run.result.plan_date)} · {run.file_name}
            </div>
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

      <div className="filters">
        <label>
          Orders due within{' '}
          <input type="number" min={1} max={52} {...weeksInputProps} style={{ width: '4.5rem' }} /> weeks
        </label>
      </div>

      {!summary || !run ? (
        !error && <p className="muted">Loading supplier summary…</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Supplier</th>
                <th>Reorder / target days</th>
                <th className="num">SKUs</th>
                <th className="num">SKUs to order</th>
                <th className="num">Cartons in window</th>
                <th>Earliest order date</th>
                <th>Flags</th>
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
                      <td>
                        {s.reorder_days} / {s.target_days}
                        {s.is_default && <span className="chip chip-amber tag">default</span>}
                      </td>
                      <td className="num">{s.sku_count}</td>
                      <td className="num">{s.skus_to_order}</td>
                      <td className="num">{fmtQty(s.cartons_in_window)}</td>
                      <td>{s.earliest_order_date ? fmtDate(s.earliest_order_date) : '–'}</td>
                      <td>
                        <span className="chips">
                          {FLAG_CODES.filter((code) => (s.flag_counts[code] ?? 0) > 0).map((code) => (
                            <span key={code} className={`chip ${flagTone(code)}`}>
                              {FLAG_LABELS[code]} {s.flag_counts[code]}
                            </span>
                          ))}
                        </span>
                      </td>
                    </tr>
                    {open && (
                      <tr className="expanded-row">
                        <td colSpan={7}>
                          {lines.length === 0 ? (
                            <span className="muted">No orders due in the next {weeks} weeks.</span>
                          ) : (
                            <table className="inner">
                              <thead>
                                <tr>
                                  <th>SAP Code</th>
                                  <th>Description</th>
                                  <th>Order date</th>
                                  <th className="num">Qty</th>
                                  <th>Arrival</th>
                                </tr>
                              </thead>
                              <tbody>
                                {lines.map(({ sku, order }) => (
                                  <tr key={`${sku.sap_code}-${order.order_date}`}>
                                    <td>{sku.sap_code}</td>
                                    <td>{sku.description}</td>
                                    <td>{fmtDate(order.order_date)}</td>
                                    <td className="num">{fmtQty(order.qty)}</td>
                                    <td>{fmtDate(order.arrival_date)}</td>
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
                  <td colSpan={7} className="muted">
                    This run has no suppliers.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          <p className="muted">
            Earliest order date covers all of a supplier&apos;s planned orders, not only those inside the window.
          </p>
        </div>
      )}
    </div>
  )
}
