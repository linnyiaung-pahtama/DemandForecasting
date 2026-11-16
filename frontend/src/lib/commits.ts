import type { City, Commit } from '../types'

/** One commit line as typed on the New plan page (cartons as text, the SAP code possibly "code — description"). */
export interface CommitLine {
  sap_code: string
  cartons: string
  arrival_week: string // the week's Monday, or '' before one is chosen
  region: City
}

/** The SAP code of a typed or picked entry: the text before " — " (the picker shows "code — description"). */
export function commitCode(text: string): string {
  return text.split('—')[0].trim()
}

function cartons(text: string): number {
  const n = Number(text.replace(/,/g, '').trim())
  return Number.isFinite(n) ? n : NaN
}

/** What stops the commits being sent, for the first line that is incomplete; null when all are ready. */
export function commitProblem(lines: CommitLine[], codes: Set<string>, weeks: Set<string>): string | null {
  for (const [i, l] of lines.entries()) {
    const where = `Commit ${i + 1}: `
    if (!codes.has(commitCode(l.sap_code))) return `${where}choose a SAP code from the Sales Forecast file.`
    if (!(cartons(l.cartons) > 0)) return `${where}enter cartons above 0.`
    if (!weeks.has(l.arrival_week)) return `${where}choose an arrival week.`
  }
  return null
}

/** Saved commits as editor lines, to change them on a calculated plan. */
export function fromCommits(commits: Commit[]): CommitLine[] {
  return commits.map((c) => ({
    sap_code: c.sap_code,
    cartons: String(c.cartons),
    arrival_week: c.arrival_week,
    region: c.region,
  }))
}

/** The lines as commits for the API. */
export function toCommits(lines: CommitLine[]): Commit[] {
  return lines.map((l) => ({
    sap_code: commitCode(l.sap_code),
    cartons: cartons(l.cartons),
    arrival_week: l.arrival_week,
    region: l.region,
  }))
}
