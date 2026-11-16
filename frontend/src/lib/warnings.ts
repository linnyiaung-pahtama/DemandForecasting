import { cityLabel, runOutMessage } from './format'
import type { ParseWarning, SkuResult } from '../types'

export type WarningSource = 'Sales Forecast file' | 'Actual Sales file' | 'Stock files' | 'Stock in Transit file'

export interface SourcedWarning {
  source: WarningSource
  warning: ParseWarning
}

export interface GroupedWarnings {
  fileLevel: SourcedWarning[] // not tied to a SKU (sap_code null): shown prominently
  perSku: SourcedWarning[]
}

/** Split a run's warnings into file-level and per-SKU ones, each labelled with the file it came from. */
export function groupWarnings(
  dataWarnings: ParseWarning[],
  salesWarnings: ParseWarning[],
  stockWarnings: ParseWarning[] = [],
  sitWarnings: ParseWarning[] = [],
): GroupedWarnings {
  const all: SourcedWarning[] = [
    ...dataWarnings.map((warning) => ({ source: 'Sales Forecast file' as const, warning })),
    ...salesWarnings.map((warning) => ({ source: 'Actual Sales file' as const, warning })),
    ...stockWarnings.map((warning) => ({ source: 'Stock files' as const, warning })),
    ...sitWarnings.map((warning) => ({ source: 'Stock in Transit file' as const, warning })),
  ]
  return {
    fileLevel: all.filter((x) => x.warning.sap_code === null),
    perSku: all.filter((x) => x.warning.sap_code !== null),
  }
}

/** One warning per SKU flagged as running out before its SIT arrives (none for older runs). */
export function runOutWarnings(skus: SkuResult[]): ParseWarning[] {
  return skus.flatMap((s) => {
    const message = runOutMessage(s)
    if (message === null) return []
    const text = message.replace(/^R/, 'r')
    return [{ sap_code: s.sap_code, column: null, message: s.city ? `${cityLabel(s.city)}: ${text}` : text }]
  })
}

/** The stock-report warnings that apply to a whole file (not one SKU): the upload page shows them in an alert. */
export function stockFileWarnings(warnings: ParseWarning[]): ParseWarning[] {
  return warnings.filter(
    (w) => w.sap_code === null && (w.message.startsWith('PG Expiry Check') || w.message.startsWith('PDG Stock List')),
  )
}
