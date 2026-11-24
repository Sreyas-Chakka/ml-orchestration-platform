import { useDispatch, useSelector } from 'react-redux'
import { Link } from 'react-router-dom'
import StatusBadge from '../components/StatusBadge'
import { fmtAgo, fmtDuration } from '../format'
import { fetchRecentRuns, fetchStats } from '../store/runsSlice'
import { usePoll } from '../usePoll'

const ORDER = ['queued', 'scheduled', 'running', 'succeeded', 'failed', 'stalled', 'cancelled']

export default function Overview() {
  const dispatch = useDispatch()
  const { stats, recent } = useSelector((s) => s.runs)
  usePoll(() => { dispatch(fetchStats()); dispatch(fetchRecentRuns()) }, 2500)
  if (!stats) return <div className="empty">Loading…</div>
  const total = ORDER.reduce((n, k) => n + (stats.runs_by_status[k] || 0), 0)
  const util = stats.capacity ? stats.active / stats.capacity : 0

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Overview</h1>
          <p className="muted">Executor <code>{stats.executor}</code> · analyst <code>{stats.analyst}</code></p>
        </div>
        <Link to="/experiments" className="btn primary">Experiments →</Link>
      </header>

      <div className="kpis">
        <div className="kpi">
          <div className="kpi-label">Cluster slots in use</div>
          <div className="kpi-value">{stats.active}<span className="muted"> / {stats.capacity}</span></div>
          <div className="meter"><div style={{ width: `${Math.min(100, util * 100)}%` }} /></div>
        </div>
        <div className="kpi">
          <div className="kpi-label">Queue depth</div>
          <div className="kpi-value">{stats.queue_depth}</div>
          <div className="muted small">{stats.queue_head.length ? `next: ${stats.queue_head.slice(0, 5).map((x) => `#${x}`).join(' ')}` : 'queue empty'}</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">Success rate · 24h</div>
          <div className="kpi-value">{stats.success_rate_24h == null ? '—' : `${(stats.success_rate_24h * 100).toFixed(0)}%`}</div>
          <div className="muted small">succeeded ÷ (succeeded + failed + stalled)</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">Experiments · runs</div>
          <div className="kpi-value">{stats.experiments}<span className="muted"> · {total}</span></div>
        </div>
      </div>

      <section className="panel">
        <h3>Runs by status</h3>
        <div className="stackbar">
          {ORDER.map((k) => {
            const n = stats.runs_by_status[k] || 0
            return n ? <div key={k} className={`seg-${k}`} style={{ flex: n }} title={`${k}: ${n}`} /> : null
          })}
        </div>
        <div className="legend">
          {ORDER.map((k) => <span key={k}><i className={`seg-${k}`} />{k} <b>{stats.runs_by_status[k] || 0}</b></span>)}
        </div>
      </section>

      <section className="panel">
        <h3>Recent runs</h3>
        <div className="scroll-x"><table className="table">
          <thead><tr><th>Run</th><th>Status</th><th>Progress</th><th>Duration</th><th>Created</th></tr></thead>
          <tbody>
            {recent.slice(0, 15).map((r) => (
              <tr key={r.id}>
                <td><Link to={`/runs/${r.id}`}>#{r.id} {r.name}</Link></td>
                <td><StatusBadge status={r.status} /></td>
                <td><div className="meter thin"><div style={{ width: `${r.progress * 100}%` }} /></div></td>
                <td>{fmtDuration(r.duration_s)}</td>
                <td className="muted">{fmtAgo(r.created_at)}</td>
              </tr>
            ))}
            {!recent.length && <tr><td colSpan={5} className="empty small">No runs yet — create an experiment and launch one.</td></tr>}
          </tbody>
        </table></div>
      </section>
    </div>
  )
}
