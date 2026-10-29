import { groupWarnings } from '../lib/warnings'
import type { ParseWarning } from '../types'

interface Props {
  dataWarnings: ParseWarning[]
  salesWarnings: ParseWarning[]
  stockWarnings: ParseWarning[]
}

/** File-level warnings are shown in full above the plan; per-SKU ones are counted in a collapsible list. */
export default function WarningsPanel({ dataWarnings, salesWarnings, stockWarnings }: Props) {
  const { fileLevel, perSku } = groupWarnings(dataWarnings, salesWarnings, stockWarnings)
  if (fileLevel.length === 0 && perSku.length === 0) return null

  return (
    <div className="warnings-panel">
      {fileLevel.length > 0 && (
        <div className="alert warn" role="status">
          <strong>{fileLevel.length === 1 ? '1 warning about the files' : `${fileLevel.length} warnings about the files`}</strong>
          <ul className="flag-messages">
            {fileLevel.map(({ source, warning }, i) => (
              <li key={i}>
                <strong>{source}: </strong>
                {warning.column ? `${warning.column}: ` : ''}
                {warning.message}
              </li>
            ))}
          </ul>
        </div>
      )}
      {perSku.length > 0 && (
        <details className="warnings">
          <summary>
            SKU warnings <span className="badge">{perSku.length}</span>
          </summary>
          <ul>
            {perSku.map(({ source, warning }, i) => (
              <li key={i}>
                <strong>
                  {[warning.sap_code, warning.column].filter(Boolean).join(' / ')} ({source}):{' '}
                </strong>
                {warning.message}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
