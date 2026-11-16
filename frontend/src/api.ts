import type {
  Commit,
  InspectResponse,
  RunListItem,
  RunRecord,
  SettingsLogEntry,
  SupplierSettings,
  SupplierSettingView,
  SupplierSummary,
} from './types'

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

// FastAPI errors are {"detail": "text"}; its own 422 validation errors have
// detail as a list of {loc, msg, ...} objects.
function detailText(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (typeof item === 'string') return item
      if (item && typeof item === 'object') {
        const { loc, msg } = item as { loc?: unknown; msg?: unknown }
        const where = Array.isArray(loc)
          ? loc.filter((p) => p !== 'body' && p !== 'query').join('.')
          : ''
        const text = typeof msg === 'string' ? msg : JSON.stringify(item)
        return where ? `${where}: ${text}` : text
      }
      return String(item)
    })
    if (parts.length > 0) return parts.join('; ')
  }
  return fallback
}

export function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  return err instanceof Error ? err.message : String(err)
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, init)
  } catch {
    throw new ApiError(0, 'Could not reach the server. Is the backend running?')
  }
  if (!response.ok) {
    const fallback = `Request failed (${response.status} ${response.statusText}).`
    let detail = fallback
    try {
      const body = (await response.json()) as { detail?: unknown }
      detail = detailText(body?.detail, fallback)
    } catch {
      // body was not JSON; keep the fallback text
    }
    throw new ApiError(response.status, detail)
  }
  return (await response.json()) as T
}

export interface UploadFiles {
  data: File
  sales: File
  pg: File
  pdg: File
  sit: File
}

function filesForm(files: UploadFiles): FormData {
  const form = new FormData()
  form.append('data_file', files.data)
  form.append('sales_file', files.sales)
  form.append('pg_file', files.pg)
  form.append('pdg_file', files.pdg)
  form.append('sit_file', files.sit)
  return form
}

export function inspectFiles(files: UploadFiles): Promise<InspectResponse> {
  return request<InspectResponse>('/api/inspect', { method: 'POST', body: filesForm(files) })
}

export function createRun(files: UploadFiles, planDate?: string, commits: Commit[] = []): Promise<RunRecord> {
  const form = filesForm(files)
  if (planDate) form.append('plan_date', planDate)
  if (commits.length > 0) form.append('commits', JSON.stringify(commits))
  return request<RunRecord>('/api/runs', { method: 'POST', body: form })
}

/** Replace a calculated plan's commits; the plan is recalculated in place with the current settings. */
export function saveCommits(runId: number, commits: Commit[]): Promise<RunRecord> {
  return request<RunRecord>(`/api/runs/${runId}/commits`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(commits),
  })
}

export function getRun(id: number): Promise<RunRecord> {
  return request<RunRecord>(`/api/runs/${id}`)
}

export function listRuns(): Promise<RunListItem[]> {
  return request<RunListItem[]>('/api/runs')
}

export function recalculate(id: number): Promise<RunRecord> {
  return request<RunRecord>(`/api/runs/${id}/recalculate`, { method: 'POST' })
}

export function getSupplierSummary(id: number): Promise<SupplierSummary[]> {
  return request<SupplierSummary[]>(`/api/runs/${id}/suppliers`)
}

export function getSettings(): Promise<SupplierSettingView[]> {
  return request<SupplierSettingView[]>('/api/settings')
}

export function saveSettings(items: SupplierSettings[]): Promise<SupplierSettingView[]> {
  return request<SupplierSettingView[]>('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(items),
  })
}

export function getSettingsLog(): Promise<SettingsLogEntry[]> {
  return request<SettingsLogEntry[]>('/api/settings/log')
}

export function exportUrl(id: number): string {
  return `/api/runs/${id}/export`
}
