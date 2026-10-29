import { fmtExact, fmtMonths, fmtQty, monthLabel, orderExplanation } from '../lib/format'
import type { ParseWarning, SkuResult } from '../types'
import StatusChip from './StatusChip'

interface Props {
  sku: SkuResult
  planDate: string
  warnings: ParseWarning[] // warnings for this SAP code only
  onClose: () => void
}

export default function SkuDetail({ sku, planDate, warnings, onClose }: Props) {
  return (
    <aside className="detail" aria-label={`Details for ${sku.sap_code}`}>
      <div className="detail-head">
        <div>
          <h2>
            {sku.sap_code} · {sku.description}
          </h2>
          <div className="muted">{sku.supplier}</div>
          <div>
            <StatusChip status={sku.status} zeroForecast={sku.zero_forecast} />
          </div>
        </div>
        <button onClick={onClose} aria-label="Close details">
          Close
        </button>
      </div>

      <dl className="facts">
        <div>
          <dt>Order qty</dt>
          <dd>{sku.order_qty === null ? '—' : `${fmtQty(sku.order_qty)} cartons`}</dd>
        </div>
        <div>
          <dt>Holding</dt>
          <dd>{sku.holding_months === null ? 'Not set' : `${fmtMonths(sku.holding_months)} months`}</dd>
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

      <h3>How this is worked out</h3>
      <ol className="steps">
        {orderExplanation(sku, planDate).map((line, i) => (
          <li key={i}>{line}</li>
        ))}
      </ol>

      {sku.monthly !== null && (
        <>
          <h3>12-month plan</h3>
          <p className="muted">Demand each month = buffer (average of the valid values above).</p>
          <table>
            <thead>
              <tr>
                <th>Month</th>
                <th className="num">Opening</th>
                <th className="num">Demand</th>
                <th className="num">Order</th>
                <th className="num">Closing</th>
              </tr>
            </thead>
            <tbody>
              {sku.monthly.map((m) => (
                <tr key={m.month}>
                  <td>{monthLabel(m.month)}</td>
                  <td className="num">{fmtExact(m.opening)}</td>
                  <td className="num">{fmtExact(m.demand)}</td>
                  <td className="num">
                    {m.order === null ? '—' : fmtQty(m.order)}
                    {m.moq_applied && <span className="chip chip-grey tag">MOQ</span>}
                  </td>
                  <td className="num">{fmtExact(m.closing)}</td>
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
