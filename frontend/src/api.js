const BASE = import.meta.env.VITE_API_URL || ''

export class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

export function getToken() {
  return localStorage.getItem('mlops_token')
}

export async function api(path, { method = 'GET', body, raw = false } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (res.status === 401 && token) {
    localStorage.removeItem('mlops_token')
    window.dispatchEvent(new Event('mlops:logout'))
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch { /* not json */ }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return null
  return raw ? res.text() : res.json()
}

export async function downloadArtifact(runId, art) {
  const res = await fetch(`${BASE}/api/runs/${runId}/artifacts/${art.id}/download`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  })
  if (!res.ok) throw new ApiError(res.status, 'Download failed')
  const url = URL.createObjectURL(await res.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: art.name })
  a.click()
  URL.revokeObjectURL(url)
}
