import {
  cityLabel,
  fmtCycle,
  fmtDate,
  fmtExact,
  fmtHolding,
  fmtQty,
  monthLabel,
  orderExplanation,
  runOutMessage,
} from '../lib/format'
import { MODE_LABEL, orderCell, skuArrivals, skuView, type PlanMode } from '../lib/mode'
import type { ParseWarning, SkuResult } from '../types'
import StatusChip from './StatusChip'

interface Props {
  sku: SkuResult
  planDate: string
  mode: PlanMode // the page's mode: the order, status, arithmetic and 12 months shown are that plan's
  warnings: ParseWarning[] // warnings for this SAP code only
  onClose: () => void
}

export default function SkuDetail({ sku, planDate, mode, warnings, onClose }: Props) {
  const view = skuView(sku, mode)
  const cycle = sku.order_cycle_weeks
  // An older run has no order plan: say so rather than show blanks next to the forecast's status.
  const noPlan = mode === 'plan' && sku.order_plan === null
  // Every planned order with its date (0 included); none when holding is not set.
  const orderLines = (view.months ?? []).flatMap((m) => m.orders)
  const arrivals = skuArrivals(sku, planDate)
  const runOut = runOutMessage(sku)
  return (
    <aside className="detail" aria-label={`Details for ${sku.sap_code}`}>
      <div className="detail-head">
        <div>
          <h2>
            {sku.sap_code} · {sku.description}
          </h2>
          {sku.city !== null && <div className="muted">{cityLabel(sku.city)}</div>}
          <div className="muted">{sku.supplier}</div>
          {!noPlan && (
            <div>
              <StatusChip status={view.status} zeroForecast={sku.zero_forecast} />
            </div>
          )}
        </div>
        <button onClick={onClose} aria-label="Close details">
          Close
        </button>
      </div>

      {noPlan && <div className="alert warn">Recalculate to see the order plan.</div>}
      {runOut && (
        <div className="alert error" role="status">
          {runOut}. Chase the delivery: a new order won&apos;t arrive before it.
        </div>
      )}

      <dl className="facts">
        {!noPlan && (
          <div>
            <dt>Order qty</dt>
            <dd>{view.orderQty === null ? '—' : `${fmtQty(view.orderQty)} cartons`}</dd>
          </div>
        )}
        <div>
          <dt>Holding</dt>
          <dd>{fmtHolding(sku.holding_days, 'Not set')}</dd>
        </div>
        <div>
          <dt>Order cycle</dt>
          <dd>{fmtCycle(cycle)}</dd>
        </div>
        <div>
          <dt>Lead time</dt>
          <dd>{sku.lead_time_days === null ? 'not set' : `${sku.lead_time_days} days`}</dd>
        </div>
        <div>
          <dt>MOQ</dt>
          <dd>{sku.moq > 0 ? `${fmtQty(sku.moq)} (principal)` : 'none'}</dd>
        </div>
        <div>
          <dt>Packing size</dt>
          <dd>{sku.packing_size === null ? '—' : fmtQty(sku.packing_size)}</dd>
        </div>
        {sku.pg_non_sellable !== null && sku.pdg_non_sellable !== null && (
          <div>
            <dt>Non-sellable</dt>
            <dd>
              PG {fmtExact(sku.pg_non_sellable)} · PDG {fmtExact(sku.pdg_non_sellable)}
            </dd>
          </div>
        )}
      </dl>

      {sku.zero_forecast && (
        <div className="alert warn">
          Zero forecast: all 3 forecast months are zero or missing. The order is calculated from actual
          sales only, so review it before ordering.
        </div>
      )}

      <h3>Demand values (cartons)</h3>
      <table>
        <thead>
          <tr>
            <th>Month</th>
            <th>Source</th>
            <th className="num">Value</th>
            <th>Valid</th>
          </tr>
        </thead>
        <tbody>
          {sku.demand_values.map((d) => (
            <tr key={`${d.source}-${d.month}`} className={d.valid ? undefined : 'muted'}>
              <td>{monthLabel(d.month)}</td>
              <td>{d.source === 'actual' ? 'Actual' : 'Sales forecast'}</td>
              <td className="num">{d.value === null ? '—' : fmtExact(d.value)}</td>
              <td aria-label={d.valid ? 'Valid' : 'Skipped'}>{d.valid ? '✓' : '✗'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">Only values above zero are counted; the rest are skipped.</p>

      <h3>Stock in transit</h3>
      {arrivals.length === 0 ? (
        <p className="muted">No stock in transit.</p>
      ) : (
        <>
          <table>
            <thead>
              <tr>
                <th>Arrives</th>
                <th className="num">Cartons</th>
              </tr>
            </thead>
            <tbody>
              {arrivals.map((a) => (
                <tr key={`${a.date}|${a.source ?? 'sit'}`}>
                  <td>
                    {fmtDate(a.date)}
                    {a.source === 'commit' && (
                      <span className="chip chip-grey tag commit-tag" title="A commit: stock agreed with the principal, not from the Stock in Transit file">
                        Commit
                      </span>
                    )}
                  </td>
                  <td className="num">{fmtExact(a.cartons)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">
            {sku.sit_arrivals === null
              ? 'Saved before the Stock in Transit file, so all SIT counts from the plan date.'
              : 'Each delivery lands on the Monday of its arrival week (the plan date if that is earlier).'}
          </p>
        </>
      )}

      <h3>How this is worked out</h3>
      <ol className="steps">
        {orderExplanation(sku, planDate, mode).map((line, i) => (
          <li key={i}>{line}</li>
        ))}
      </ol>

      {view.months !== null && (
        <>
          <h3>{MODE_LABEL[mode]}</h3>
          <p className="muted">
            Demand each month = avg sales (the average of the valid values above).
            {mode === 'plan' &&
              cycle !== null &&
              ` Orders are placed ${fmtCycle(cycle)} from the plan date; each month is the total of its orders, and · marks months without one.`}
          </p>
          <table>
            <thead>
              <tr>
                <th>Month</th>
                <th className="num">Opening</th>
                {mode === 'plan' && <th className="num">Arrivals</th>}
                <th className="num">Demand</th>
                <th className="num">Order</th>
                <th className="num">Closing</th>
              </tr>
            </thead>
            <tbody>
              {view.months.map((m) => {
                const kind = orderCell(m)
                return (
                  <tr key={m.month} className={kind === 'not-order-month' ? 'muted' : undefined}>
                    <td>{monthLabel(m.month)}</td>
                    <td className="num">{fmtExact(m.opening)}</td>
                    {mode === 'plan' && (
                      <td className="num">{m.arrivals == null ? '—' : fmtExact(m.arrivals)}</td>
                    )}
                    <td className="num">{fmtExact(m.demand)}</td>
                    <td className="num" title={kind === 'not-order-month' ? 'Not an order month' : undefined}>
                      {kind === 'blocked' ? '—' : kind === 'not-order-month' ? '·' : fmtQty(m.order ?? 0)}
                      {m.moq_applied && <span className="chip chip-grey tag">MOQ</span>}
                    </td>
                    <td className="num">{fmtExact(m.closing)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </>
      )}

      {mode === 'plan' && orderLines.length > 0 && (
        <>
          <h3>Orders</h3>
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th className="num">Quantity</th>
              </tr>
            </thead>
            <tbody>
              {orderLines.map((o) => (
                <tr key={o.date} className={o.qty === 0 ? 'muted' : undefined}>
                  <td>{fmtDate(o.date)}</td>
                  <td className="num">
                    {fmtQty(o.qty)}
                    {o.moq_applied && <span className="chip chip-grey tag">MOQ</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {warnings.length > 0 && (
        <>
          <h3>Warnings</h3>
          <ul className="flag-messages">
            {warnings.map((w, i) => (
              <li key={i}>
                {w.column ? `${w.column}: ` : ''}
                {w.message}
              </li>
            ))}
          </ul>
        </>
      )}
    </aside>
  )
}
