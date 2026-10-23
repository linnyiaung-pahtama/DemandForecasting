import type {
  InspectResponse,
  RunListItem,
  RunRecord,
  SupplierSetting,
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

export function inspectFile(file: File): Promise<InspectResponse> {
  const form = new FormData()
  form.append('file', file)
  return request<InspectResponse>('/api/inspect', { method: 'POST', body: form })
}

export function createRun(file: File, planDate?: string): Promise<RunRecord> {
  const form = new FormData()
  form.append('file', file)
  if (planDate) form.append('plan_date', planDate)
  return request<RunRecord>('/api/runs', { method: 'POST', body: form })
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

export function getSupplierSummary(id: number, windowWeeks: number): Promise<SupplierSummary[]> {
  return request<SupplierSummary[]>(`/api/runs/${id}/suppliers?window_weeks=${windowWeeks}`)
}

export function getSettings(): Promise<SupplierSettingView[]> {
  return request<SupplierSettingView[]>('/api/settings')
}

export function saveSettings(items: SupplierSetting[]): Promise<SupplierSettingView[]> {
  return request<SupplierSettingView[]>('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(items),
  })
}

export function exportUrl(id: number, windowWeeks: number): string {
  return `/api/runs/${id}/export?window_weeks=${windowWeeks}`
}
