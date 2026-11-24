export function fmtDuration(s) {
  if (s == null) return '—'
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${Math.round(s % 60)}s`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

export function fmtAgo(iso) {
  if (!iso) return '—'
  const t = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z').getTime()
  const s = Math.max(0, (Date.now() - t) / 1000)
  if (s < 60) return `${Math.floor(s)}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export function fmtNum(v, digits = 4) {
  if (v == null || Number.isNaN(v)) return '—'
  if (typeof v !== 'number') return String(v)
  if (Number.isInteger(v)) return String(v)
  return v.toFixed(digits)
}

export function fmtBytes(n) {
  if (!n) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)))
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`
}

/** Parse "0.01, 0.1, 1" / "8,16" / "true,false" into typed values for sweep grids. */
export function parseList(text) {
  return text
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => {
      if (s === 'true') return true
      if (s === 'false') return false
      if (s === 'null') return null
      const n = Number(s)
      return Number.isNaN(n) ? s : n
    })
}

export const ACTIVE = new Set(['queued', 'scheduled', 'running'])
export const RUN_COLORS = ['#818cf8', '#34d399', '#fbbf24', '#f472b6', '#38bdf8', '#fb7185', '#a3e635', '#c084fc', '#2dd4bf', '#fb923c', '#e879f9', '#94a3b8']
