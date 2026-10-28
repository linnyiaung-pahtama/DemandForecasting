import type { ParseWarning } from '../types'

export type WarningSource = 'Data file' | 'Sales export'

export interface SourcedWarning {
  source: WarningSource
  warning: ParseWarning
}

export interface GroupedWarnings {
  fileLevel: SourcedWarning[] // not tied to a SKU (sap_code null): shown prominently
  perSku: SourcedWarning[]
}

/** Split a run's warnings into file-level and per-SKU ones, each labelled with the file it came from. */
export function groupWarnings(dataWarnings: ParseWarning[], salesWarnings: ParseWarning[]): GroupedWarnings {
  const all: SourcedWarning[] = [
    ...dataWarnings.map((warning) => ({ source: 'Data file' as const, warning })),
    ...salesWarnings.map((warning) => ({ source: 'Sales export' as const, warning })),
  ]
  return {
    fileLevel: all.filter((x) => x.warning.sap_code === null),
    perSku: all.filter((x) => x.warning.sap_code !== null),
  }
}
