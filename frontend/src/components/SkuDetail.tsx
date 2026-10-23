import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { SkuPlan } from '../types'
import { fmtDate, fmtQty, orderReason } from '../lib/format'
import FlagChips from './FlagChips'

export default function SkuDetail({ sku, onClose }: { sku: SkuPlan; onClose: () => void }) {
  const data = sku.weeks.map((w) => ({
    label: `W${w.week}`,
    closing_stock: w.closing_stock,
    reorder_qty: w.reorder_qty,
    target_qty: w.target_qty,
    arrivals: w.arrivals,
  }))

  return (
    <aside className="detail" aria-label={`Details for ${sku.sap_code}`}>
      <div className="detail-head">
        <div>
          <h2>
            {sku.sap_code} · {sku.description}
          </h2>
          <div className="muted">{sku.supplier}</div>
        </div>
        <button onClick={onClose} aria-label="Close details">
          Close
        </button>
      </div>

      <dl className="facts">
        <div>
          <dt>Sellable</dt>
          <dd>{fmtQty(sku.sellable)}</dd>
        </div>
        <div>
          <dt>SIT</dt>
          <dd>{fmtQty(sku.sit)}</dd>
        </div>
        <div>
          <dt>Days of cover</dt>
          <dd>{sku.days_of_cover === null ? '–' : fmtQty(sku.days_of_cover)}</dd>
        </div>
        <div>
          <dt>Lead time</dt>
          <dd>{sku.lead_time_days === null ? '–' : `${sku.lead_time_days} days`}</dd>
        </div>
        <div>
          <dt>MOQ</dt>
          <dd>{sku.moq > 0 ? fmtQty(sku.moq) : 'none'}</dd>
        </div>
        <div>
          <dt>Forecast in plan</dt>
          <dd>{fmtQty(sku.total_forecast)}</dd>
        </div>
      </dl>

      <h3>Flags</h3>
      {sku.flags.length === 0 ? (
        <p className="muted">No flags.</p>
      ) : (
        <ul className="flag-messages">
          {sku.flags.map((f) => (
            <li key={f.code}>
              <FlagChips flags={[f]} /> {f.message}
            </li>
          ))}
        </ul>
      )}

      <h3>Planned orders</h3>
      {sku.orders.length === 0 ? (
        <p className="muted">No orders needed in the planning horizon.</p>
      ) : (
        <ul className="orders">
          {sku.orders.map((o) => (
            <li key={o.order_date}>
              <strong>
                {fmtDate(o.order_date)}: {fmtQty(o.qty)} cartons
              </strong>{' '}
              <span className="muted">(arrives {fmtDate(o.arrival_date)})</span>
              <div>{orderReason(o)}</div>
            </li>
          ))}
        </ul>
      )}

      <h3>Projected stock</h3>
      <div className="chart">
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" />
            <YAxis />
            <Tooltip />
            <Legend />
            <Bar dataKey="arrivals" name="Arrivals" fill="#9bbcf0" />
            <Line type="monotone" dataKey="closing_stock" name="Closing stock" stroke="#1f5fbf" dot={false} strokeWidth={2} />
            <Line type="stepAfter" dataKey="reorder_qty" name="Reorder level" stroke="#d98a00" dot={false} strokeDasharray="5 3" />
            <Line type="stepAfter" dataKey="target_qty" name="Target level" stroke="#2c8a4b" dot={false} strokeDasharray="5 3" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <h3>Week by week</h3>
      <table>
        <thead>
          <tr>
            <th className="num">Week</th>
            <th>Start</th>
            <th className="num">Demand</th>
            <th className="num">Arrivals</th>
            <th className="num">Closing stock</th>
            <th className="num">Lost</th>
          </tr>
        </thead>
        <tbody>
          {sku.weeks.map((w) => (
            <tr key={w.week}>
              <td className="num">{w.week}</td>
              <td>{fmtDate(w.start)}</td>
              <td className="num">{fmtQty(w.demand)}</td>
              <td className="num">{w.arrivals > 0 ? fmtQty(w.arrivals) : '–'}</td>
              <td className="num">{fmtQty(w.closing_stock)}</td>
              <td className="num">{w.lost > 0 ? fmtQty(w.lost) : '–'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </aside>
  )
}
