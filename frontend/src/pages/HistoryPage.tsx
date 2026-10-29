import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { errorText, listRuns } from '../api'
import { fmtDate } from '../lib/format'
import type { RunListItem } from '../types'

export default function HistoryPage() {
  const [runs, setRuns] = useState<RunListItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listRuns()
      .then((r) => {
        if (!cancelled) setRuns(r)
      })
      .catch((err) => {
        if (!cancelled) setError(errorText(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div>
      <h2>Run history</h2>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {!runs ? (
        !error && <p className="muted">Loading runs…</p>
      ) : runs.length === 0 ? (
        <p className="muted">
          No runs yet. <Link to="/">Upload files</Link> to create one.
        </p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th className="num">Run #</th>
                <th>Created</th>
                <th>Data file</th>
                <th>Sales export</th>
                <th>PG Expiry Check</th>
                <th>PDG Stock List</th>
                <th>Plan date</th>
                <th className="num">SKUs</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td className="num">
                    <Link to={`/runs/${r.id}`}>{r.id}</Link>
                  </td>
                  <td>
                    <Link to={`/runs/${r.id}`}>{fmtDate(r.created_at)}</Link>
                  </td>
                  <td>
                    <Link to={`/runs/${r.id}`}>{r.file_name}</Link>
                  </td>
                  <td>{r.sales_file_name}</td>
                  <td>{r.pg_file_name ?? '—'}</td>
                  <td>{r.pdg_file_name ?? '—'}</td>
                  <td>{fmtDate(r.plan_date)}</td>
                  <td className="num">{r.sku_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
