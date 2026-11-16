import { useId, useMemo } from 'react'
import { commitCode, type CommitLine } from '../lib/commits'
import type { City, SkuOption } from '../types'

interface Props {
  lines: CommitLine[]
  onChange: (lines: CommitLine[]) => void
  skus: SkuOption[] // the SKUs a commit can be for (the plan's Sales Forecast SKUs)
  weeks: { monday: string; label: string }[] // the arrival weeks offered
  disabled?: boolean
  issue: string | null // what stops the lines being used, shown under them
}

/**
 * The commit lines editor (New plan, and Edit commits on a calculated plan): SAP code (picked from the SKUs), cartons,
 * estimated arrival week and region per line, with Add commit and Remove.
 */
export default function CommitEditor({ lines, onChange, skus, weeks, disabled = false, issue }: Props) {
  const listId = useId()
  const skuByCode = useMemo(() => new Map(skus.map((s) => [s.sap_code, s])), [skus])

  function update(i: number, change: Partial<CommitLine>) {
    onChange(lines.map((c, j) => (j === i ? { ...c, ...change } : c)))
  }

  return (
    <>
      <datalist id={listId}>
        {skus.map((s) => (
          <option key={s.sap_code} value={`${s.sap_code} — ${s.description} (${s.supplier})`} />
        ))}
      </datalist>
      {lines.length > 0 && (
        <table className="commit-table">
          <colgroup>
            <col />
            <col className="c-cartons" />
            <col className="c-week" />
            <col className="c-region" />
            <col className="c-remove" />
          </colgroup>
          <thead>
            <tr>
              <th>SAP Code</th>
              <th className="num">Cartons</th>
              <th>Estimated arrival week</th>
              <th>Region</th>
              <th aria-label="Remove" />
            </tr>
          </thead>
          <tbody>
            {lines.map((c, i) => {
              const picked = skuByCode.get(commitCode(c.sap_code))
              return (
                <tr key={i}>
                  <td>
                    <input
                      type="text"
                      list={listId}
                      aria-label={`SAP code for commit ${i + 1}`}
                      placeholder="Type a code or description"
                      value={c.sap_code}
                      onChange={(e) => {
                        // A pick from the list ("code — description (principal)") keeps just the code; the
                        // description shows on the line below.
                        const code = commitCode(e.target.value)
                        const value = e.target.value.includes('—') && skuByCode.has(code) ? code : e.target.value
                        update(i, { sap_code: value })
                      }}
                      disabled={disabled}
                    />
                    {picked && (
                      <div className="commit-sku" title={`${picked.description} (${picked.supplier})`}>
                        {picked.description} ({picked.supplier})
                      </div>
                    )}
                  </td>
                  <td className="num">
                    <input
                      type="text"
                      inputMode="decimal"
                      aria-label={`Cartons for commit ${i + 1}`}
                      value={c.cartons}
                      onChange={(e) => update(i, { cartons: e.target.value })}
                      disabled={disabled}
                    />
                  </td>
                  <td>
                    <select
                      aria-label={`Arrival week for commit ${i + 1}`}
                      value={c.arrival_week}
                      onChange={(e) => update(i, { arrival_week: e.target.value })}
                      disabled={disabled}
                    >
                      <option value="">Choose week</option>
                      {weeks.map((w) => (
                        <option key={w.monday} value={w.monday}>
                          {w.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <select
                      aria-label={`Region for commit ${i + 1}`}
                      value={c.region}
                      onChange={(e) => update(i, { region: e.target.value as City })}
                      disabled={disabled}
                    >
                      <option value="YGN">Yangon</option>
                      <option value="MDY">Mandalay</option>
                    </select>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => onChange(lines.filter((_, j) => j !== i))}
                      disabled={disabled}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      <button
        type="button"
        onClick={() => onChange([...lines, { sap_code: '', cartons: '', arrival_week: '', region: 'YGN' }])}
        disabled={disabled}
      >
        Add commit
      </button>
      {issue && <p className="field-error">{issue}</p>}
    </>
  )
}
