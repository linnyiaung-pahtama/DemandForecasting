import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { errorText, exportUrl, getRun, recalculate } from '../api'
import ColumnSwitch, { type ColumnView } from '../components/ColumnSwitch'
import CommitsPanel from '../components/CommitsPanel'
import ModeSwitch from '../components/ModeSwitch'
import SkuDetail from '../components/SkuDetail'
import StatusChip from '../components/StatusChip'
import WarningsPanel from '../components/WarningsPanel'
import { filterSkus } from '../lib/filters'
import type { SkuFilter } from '../lib/filters'
import {
  cityLabel,
  demandColumns,
  fmtCycleShort,
  fmtDate,
  fmtHolding,
  fmtQty,
  hasMonthly,
  isLegacyRun,
  monthLabel,
  runOutMessage,
  statusLabel,
} from '../lib/format'
import {
  arrivalsByWeek,
  commitCartons,
  hasOrderPlan,
  LEVEL_LABEL,
  MODE_LABEL,
  modeCounts,
  modeQuery,
  addWeeks,
  orderCell,
  orderDateLabel,
  ordersByWeek,
  placedOrders,
  planWeeks,
  rowKey,
  skuArrivals,
  skuView,
  type WeekArrivals,
} from '../lib/mode'
import { usePlanMode } from '../lib/usePlanMode'
import { runOutWarnings } from '../lib/warnings'
import type { City, MonthPlan, RunRecord, SkuStatus } from '../types'

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
  const [city, setCity] = useState<City | null>(null)
  // The selected plan row's key (SAP code + city; see rowKey).
  const [selected, setSelected] = useState<string | null>(null)
  const [mode, setMode] = usePlanMode()
  const [columns, setColumns] = useState<ColumnView>('months')

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
    const f: SkuFilter = { supplier, status, zeroForecastOnly, search, city }
    return filterSkus(result.skus, f, mode)
  }, [result, supplier, status, zeroForecastOnly, search, city, mode])

  // A run split by city has City values; older runs have one combined row per SKU and no City filter.
  const byCity = useMemo(() => (result?.skus ?? []).some((s) => s.city !== null), [result])

  const selectedSku = useMemo(
    () => (result && selected ? (result.skus.find((s) => rowKey(s) === selected) ?? null) : null),
    [result, selected],
  )

  const selectedWarnings = useMemo(() => {
    if (!run || !selectedSku) return []
    return [
      ...run.parsed.warnings,
      ...run.actual.warnings,
      ...(run.stock?.warnings ?? []),
      ...(run.stock?.sit_warnings ?? []),
    ].filter((w) => w.sap_code === selectedSku.sap_code)
  }, [run, selectedSku])

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

  const filtersActive = supplier !== null || status !== null || zeroForecastOnly || search !== '' || city !== null

  function clearFilters() {
    setCity(null)
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
  const counts = modeCounts(result, mode)
  // An older run has no order plan: its order-plan view asks for a recalculation instead.
  const showTable = hasMonthly(result) && (mode === 'forecast' || hasOrderPlan(result))
  // Week columns only exist for the order plan; the order demand forecast has no order dates.
  const weeks = mode === 'plan' && columns === 'weeks'
  const weekGroups = planWeeks(result.plan_months)
  const planColumns = weeks ? weekGroups.reduce((n, g) => n + g.weeks.length, 0) : result.plan_months.length
  // product 3 + city + settings 4 + sales months + stock 4 + order columns + total + status
  const columnCount = 4 + 4 + result.actual_months.length + result.forecast_months.length + 4 + planColumns + 2
  // In week view the header has a third row (the weeks), so the other headers span one more row.
  const headRows = weeks ? 3 : 2

  return (
    <div className="plan">
      <div className="plan-head">
        <div>
          <h2>Order plan</h2>
          <div className="muted">Plan date {fmtDate(result.plan_date)}</div>
          <div className="muted">
            From {run.file_name} + {run.sales_file_name}
            {run.pg_file_name !== null && run.pdg_file_name !== null && ` + ${run.pg_file_name} + ${run.pdg_file_name}`}
            {run.sit_file_name !== null && ` + ${run.sit_file_name}`}
          </div>
          {isLegacyRun(result) && (
            <div className="muted">
              Saved before MOQ and lead time moved to Principal settings — Recalculate to use the current settings.
            </div>
          )}
        </div>
        <div className="plan-actions">
          <Link className="btn" to={`/runs/${runId}/suppliers${modeQuery(mode)}`}>
            Principal summary
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
          {blocked === 1 ? '1 principal has no holding set, so its SKUs are' : `${blocked} principals have no holding set, so their SKUs are`}{' '}
          not calculated — set holding in <Link to="/settings">Principal settings</Link>
        </div>
      )}

      <WarningsPanel
        dataWarnings={run.parsed.warnings}
        salesWarnings={run.actual.warnings}
        stockWarnings={run.stock?.warnings ?? []}
        sitWarnings={[...(run.stock?.sit_warnings ?? []), ...runOutWarnings(result.skus)]}
      />

      <CommitsPanel run={run} selected={selected} onSelect={setSelected} onSaved={setRun} />

      <div className="switches">
        <ModeSwitch mode={mode} onChange={setMode} />
        {mode === 'plan' && <ColumnSwitch view={columns} onChange={setColumns} />}
      </div>

      <div className="cards">
        {CARDS.map((c) => (
          <button
            key={c.key}
            className={`count-card${isActive(c) ? ' active' : ''}`}
            onClick={() => onCardClick(c)}
            aria-pressed={isActive(c)}
          >
            <span className="count">{counts === null ? '—' : (counts[c.key] ?? 0)}</span>
            <span>{c.label}</span>
          </button>
        ))}
      </div>

      <div className="filters">
        <label>
          Principal{' '}
          <select value={supplier ?? ''} onChange={(e) => setSupplier(e.target.value || null)}>
            <option value="">All principals</option>
            {suppliers.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        {byCity && (
          <label>
            Region{' '}
            <select value={city ?? ''} onChange={(e) => setCity((e.target.value || null) as City | null)}>
              <option value="">All regions</option>
              <option value="YGN">Yangon</option>
              <option value="MDY">Mandalay</option>
            </select>
          </label>
        )}
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
          {rows.length} of {result.skus.length} {byCity ? 'rows (a row per SKU per region)' : 'SKUs'}
        </span>
        {filtersActive && <button onClick={clearFilters}>Clear filters</button>}
      </div>

      <div className={`plan-body${selectedSku ? ' with-detail' : ''}`}>
        <div className="table-wrap">
          {showTable ? (
            <>
              <table className="plan-table">
                <thead>
                  <tr>
                    <th rowSpan={headRows} className="stick stick-1">Principal</th>
                    <th rowSpan={headRows} className="stick stick-2">SAP Code</th>
                    <th rowSpan={headRows} className="stick stick-3">Description</th>
                    <th rowSpan={headRows}>Region</th>
                    <th colSpan={4} className="group group-start">Principal settings</th>
                    <th colSpan={result.actual_months.length} className="group group-start">Actual sales</th>
                    <th colSpan={result.forecast_months.length} className="group group-start">Sales forecast</th>
                    <th colSpan={4} className="group group-start">Stock</th>
                    <th colSpan={planColumns} className="group group-start">
                      {MODE_LABEL[mode]}
                    </th>
                    <th rowSpan={headRows} className="num group-start">Total</th>
                    <th rowSpan={headRows}>Status</th>
                  </tr>
                  <tr>
                    <th rowSpan={headRows - 1} className="num group-start">MOQ</th>
                    <th rowSpan={headRows - 1} className="num">Holding</th>
                    <th rowSpan={headRows - 1} className="num">Lead time</th>
                    <th rowSpan={headRows - 1} className="num">Order cycle</th>
                    {[...result.actual_months, ...result.forecast_months].map((m, i) => (
                      <th
                        key={`${i < result.actual_months.length ? 'a' : 'f'}-${m}`}
                        rowSpan={headRows - 1}
                        className={`num${i === 0 || i === result.actual_months.length ? ' group-start' : ''}`}
                      >
                        {monthLabel(m)}
                      </th>
                    ))}
                    <th rowSpan={headRows - 1} className="num group-start" title="Average monthly sales">
                      Avg sales
                    </th>
                    <th rowSpan={headRows - 1} className="num" title="Avg sales ÷ 30 × holding days, in cartons">
                      Buffer
                    </th>
                    <th rowSpan={headRows - 1} className="num">Available</th>
                    <th rowSpan={headRows - 1} className="num">{LEVEL_LABEL[mode]}</th>
                    {weekGroups.map((g, i) => (
                      <th
                        key={g.month}
                        colSpan={weeks ? g.weeks.length : 1}
                        className={`num${i === 0 || weeks ? ' group-start' : ''}${weeks ? ' week-month' : ''}`}
                      >
                        {monthLabel(g.month)}
                      </th>
                    ))}
                  </tr>
                  {weeks && (
                    <tr>
                      {weekGroups.flatMap((g) =>
                        g.weeks.map((w, j) => (
                          <th key={w} className={`num${j === 0 ? ' group-start' : ''}`} title={weekRange(w)}>
                            {fmtDate(w).replace(/ \d{4}$/, '')}
                          </th>
                        )),
                      )}
                    </tr>
                  )}
                </thead>
                <tbody>
                  {rows.map((s) => {
                    const view = skuView(s, mode)
                    return (
                      <tr
                        key={rowKey(s)}
                        className={`clickable${rowKey(s) === selected ? ' selected' : ''}`}
                        onClick={() => setSelected(rowKey(s) === selected ? null : rowKey(s))}
                      >
                        <td className="stick stick-1">{s.supplier}</td>
                        <td className="stick stick-2">{s.sap_code}</td>
                        <td className="stick stick-3">{s.description}</td>
                        <td>{cityLabel(s.city)}</td>
                        <td className="num group-start">{fmtQty(s.moq)}</td>
                        <td className="num">{fmtHolding(s.holding_days)}</td>
                        <td className="num">{s.lead_time_days === null ? '—' : `${s.lead_time_days} days`}</td>
                        <td className="num">{fmtCycleShort(s.order_cycle_weeks)}</td>
                        {demandColumns(s, result.actual_months, result.forecast_months).map((d, i) => (
                          <td
                            key={i}
                            className={`num${i === 0 || i === result.actual_months.length ? ' group-start' : ''}${d?.valid ? '' : ' skipped'}`}
                            title={d?.valid ? undefined : 'Not counted in the buffer (zero, negative or missing)'}
                          >
                            {d === null || d.value === null ? '—' : fmtQty(d.value)}
                          </td>
                        ))}
                        <td className="num group-start">{s.avg_sales === null ? '—' : fmtQty(s.avg_sales)}</td>
                        <td className="num">{s.buffer === null ? '—' : fmtQty(s.buffer)}</td>
                        <td className="num">{fmtQty(s.available)}</td>
                        <td className="num">{view.level === null ? '—' : fmtQty(view.level)}</td>
                        {weeks ? (
                          <WeekCells
                            months={view.months ?? []}
                            groups={weekGroups}
                            arrivals={arrivalsByWeek(skuArrivals(s, result.plan_date))}
                          />
                        ) : (
                          (view.months ?? []).map((m, i) => <MonthCell key={m.month} month={m} groupStart={i === 0} />)
                        )}
                        <td className="num group-start">{view.total === null ? '—' : fmtQty(view.total)}</td>
                        <td>
                          <StatusChip status={view.status} zeroForecast={s.zero_forecast} />
                          {commitCartons(s) > 0 && (
                            <span
                              className="chip chip-grey tag"
                              title={`${fmtQty(commitCartons(s))} cartons committed`}
                            >
                              Commit
                            </span>
                          )}
                          {s.runs_out_on && (
                            <span className="chip chip-red tag" title={runOutMessage(s) ?? undefined}>
                              Runs out before SIT
                            </span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                  {rows.length === 0 && (
                    <tr>
                      <td colSpan={columnCount} className="muted">
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
                Avg sales is the average of the sales months above zero (greyed months are skipped); buffer = avg sales
                ÷ 30 × holding days, in cartons.{' '}
                {mode === 'plan'
                  ? "Each principal is ordered from every order cycle (in weeks), starting on the plan date: each order brings stock (sellable plus SIT still on its way) up to the order-up-to level, buffer + avg sales × (cycle weeks × 12 ÷ 52 − 1), never less than one cycle's sales. Stock in transit joins the stock on hand on the Monday of its arrival week. In Months view a cell lists each order with its date and · marks months without an order. Weeks view has one column per Monday-to-Sunday week, headed by its Monday and placed under the month that Monday falls in, so orders a cycle apart are always the same number of columns apart; it also shows the SIT arriving in each week."
                  : "Each month's order brings stock (sellable plus SIT) back up to the buffer, which is the target."}{' '}
                Click a row to see the arithmetic.
              </p>
            </>
          ) : (
            <p className="muted">
              {hasMonthly(result) ? 'Recalculate to see the order plan.' : 'Recalculate to see the 12-month plan.'}
            </p>
          )}
        </div>
        {selectedSku && (
          <SkuDetail
            sku={selectedSku}
            planDate={result.plan_date}
            mode={mode}
            warnings={selectedWarnings}
            onClose={() => setSelected(null)}
          />
        )}
      </div>
    </div>
  )
}

/**
 * One month's order: "—" when no order is calculated, a muted dot between order months, else the order. In the
 * order plan each order placed in the month is listed with its date ("7 Dec").
 */
function MonthCell({ month, groupStart }: { month: MonthPlan; groupStart: boolean }) {
  const kind = orderCell(month)
  const placed = placedOrders(month)
  if (kind === 'order' && placed.length > 0) {
    return (
      <td className={`num order-qty${groupStart ? ' group-start' : ''}`}>
        {placed.map((o) => (
          <div key={o.date} className="order-line">
            <span className="qty">{fmtQty(o.qty)}</span>
            {o.moq_applied && <span className="chip chip-grey tag">MOQ</span>}
            <span className="order-week">{orderDateLabel(o)}</span>
          </div>
        ))}
      </td>
    )
  }
  if (kind === 'order') return <OrderCell qty={month.order} moqApplied={month.moq_applied} groupStart={groupStart} />
  return (
    <td
      className={`num${groupStart ? ' group-start' : ''}${kind === 'not-order-month' ? ' not-order' : ''}`}
      title={kind === 'not-order-month' ? 'Not an order month' : undefined}
    >
      {kind === 'blocked' ? '—' : '·'}
    </td>
  )
}

/** The days a week column covers, e.g. "30 Nov – 6 Dec 2026", for its header's hover text. */
function weekRange(monday: string): string {
  const sunday = new Date(Date.parse(`${addWeeks(monday, 1)}T00:00:00Z`) - 24 * 60 * 60 * 1000).toISOString().slice(0, 10)
  return `${fmtDate(monday).replace(/ \d{4}$/, '')} – ${fmtDate(sunday)}`
}

/**
 * The week columns of one SKU's order plan: the orders placed in each Monday-to-Sunday week ("—" in every week when
 * no order is calculated, blank in a week without an order), then the SIT arriving that week ("+5,250 arriving").
 * Each month's first week starts a column group.
 */
function WeekCells({
  months,
  groups,
  arrivals,
}: {
  months: MonthPlan[]
  groups: { month: string; weeks: string[] }[]
  arrivals: Map<string, WeekArrivals>
}) {
  const blocked = months.some((m) => m.order === null)
  const byWeek = ordersByWeek(months)
  return (
    <>
      {groups.flatMap((g) =>
        g.weeks.map((w, j) => {
          const start = j === 0 ? ' group-start' : ''
          const lines = byWeek.get(w) ?? []
          const arriving = arrivals.get(w) ?? { sit: 0, commit: 0 }
          const arrivalLine = (arriving.sit !== 0 || arriving.commit !== 0) && (
            <>
              {arriving.sit !== 0 && (
                <div className="arrival-line" title={`Stock in transit arriving the week of ${fmtDate(w)}`}>
                  +{fmtQty(arriving.sit)} arriving
                </div>
              )}
              {arriving.commit !== 0 && (
                <div className="arrival-line" title={`Commit arriving the week of ${fmtDate(w)}`}>
                  +{fmtQty(arriving.commit)} committed
                </div>
              )}
            </>
          )
          if (blocked) {
            return (
              <td key={w} className={`num${start}`}>
                —{arrivalLine}
              </td>
            )
          }
          if (lines.length === 0) {
            return (
              <td key={w} className={`num${start}`}>
                {arrivalLine}
              </td>
            )
          }
          const placed = lines.some((o) => o.qty > 0)
          return (
            <td key={w} className={`num${start}${placed ? ' order-qty' : ''}`} title={lines.map((o) => fmtDate(o.date)).join(', ')}>
              {lines.map((o) => (
                <div key={o.date}>
                  {o.qty > 0 ? <span className="qty">{fmtQty(o.qty)}</span> : fmtQty(o.qty)}
                  {o.moq_applied && <span className="chip chip-grey tag">MOQ</span>}
                </div>
              ))}
              {arrivalLine}
            </td>
          )
        }),
      )}
    </>
  )
}

/** An order quantity cell: quantities above zero get the turmeric tag so what needs buying stands out. */
function OrderCell({ qty, moqApplied, groupStart }: { qty: number | null; moqApplied: boolean; groupStart: boolean }) {
  return (
    <td className={`num${groupStart ? ' group-start' : ''}${qty !== null && qty > 0 ? ' order-qty' : ''}`}>
      {qty === null ? '—' : qty > 0 ? <span className="qty">{fmtQty(qty)}</span> : fmtQty(qty)}
      {moqApplied && <span className="chip chip-grey tag">MOQ</span>}
    </td>
  )
}