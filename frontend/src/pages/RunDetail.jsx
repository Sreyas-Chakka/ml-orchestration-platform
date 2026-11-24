import { useEffect, useRef } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Link, useParams } from 'react-router-dom'
import { downloadArtifact } from '../api'
import MetricChart from '../components/MetricChart'
import StatusBadge from '../components/StatusBadge'
import { ACTIVE, fmtAgo, fmtBytes, fmtDuration, fmtNum } from '../format'
import { selectCan, selectUser } from '../store/authSlice'
import { cancelRun, fetchLogs, fetchRun, retryRun } from '../store/runsSlice'
import { usePoll } from '../usePoll'

export default function RunDetail() {
  const id = Number(useParams().id)
  const dispatch = useDispatch()
  const d = useSelector((s) => s.runs.detail[id])
  const logs = useSelector((s) => s.runs.logs[id])
  const user = useSelector(selectUser)
  const canAct = useSelector(selectCan('researcher'))
  const live = !d || ACTIVE.has(d.run.status)
  const logRef = useRef(null)

  usePoll(() => { dispatch(fetchRun(id)); dispatch(fetchLogs(id)) }, live ? 1500 : null, [id, live])
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight }, [logs])

  if (!d) return <div className="empty">Loading…</div>
  const { run, metrics, events, artifacts } = d
  const mine = user && (user.role === 'admin' || user.id === run.created_by_id)
  const keys = Object.keys(metrics)
  const groups = [
    ['Loss', keys.filter((k) => k.includes('loss'))],
    ['Accuracy', keys.filter((k) => k.includes('acc'))],
    ...keys.filter((k) => !k.includes('loss') && !k.includes('acc')).map((k) => [k, [k]]),
  ].filter(([, ks]) => ks.length)

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="crumbs"><Link to={`/experiments/${run.experiment_id}`}>Experiment #{run.experiment_id}</Link> /</div>
          <h1>Run #{run.id} <StatusBadge status={run.status} /></h1>
          <p className="muted">{run.name}</p>
        </div>
        {canAct && mine && (
          <div className="row">
            {ACTIVE.has(run.status) && <button className="btn danger" onClick={() => dispatch(cancelRun(run.id))}>Cancel</button>}
            {['failed', 'stalled', 'cancelled'].includes(run.status) && <button className="btn" onClick={() => dispatch(retryRun(run.id))}>↻ Retry</button>}
          </div>
        )}
      </header>

      {run.error && <div className="error block"><b>Error:</b> {run.error}</div>}

      <div className="kpis">
        <div className="kpi"><div className="kpi-label">Progress</div><div className="kpi-value">{Math.round(run.progress * 100)}%</div>
          <div className="meter"><div style={{ width: `${run.progress * 100}%` }} /></div></div>
        <div className="kpi"><div className="kpi-label">Duration</div><div className="kpi-value">{fmtDuration(run.duration_s)}</div>
          <div className="muted small">heartbeat {fmtAgo(run.last_heartbeat_at)}</div></div>
        <div className="kpi"><div className="kpi-label">Executor</div><div className="kpi-value small-v">{run.executor}</div>
          <div className="muted small mono">{run.executor_ref || '—'}</div></div>
        <div className="kpi"><div className="kpi-label">Attempt</div><div className="kpi-value">{run.attempt + 1}<span className="muted"> / {run.max_retries + 1}</span></div>
          <div className="muted small">priority {run.priority}</div></div>
      </div>

      <div className="charts">
        {groups.map(([title, ks]) => (
          <MetricChart key={title} title={title} series={ks.map((k, i) => ({ id: i, label: k, points: metrics[k] }))} />
        ))}
        {!groups.length && <div className="panel empty small">Metrics appear once the trainer reports its first epoch.</div>}
      </div>

      <div className="split">
        <section className="panel">
          <h3>Config</h3>
          <table className="kv">
            <tbody>{Object.entries(run.config).map(([k, v]) => <tr key={k}><td className="mono muted">{k}</td><td className="mono">{JSON.stringify(v)}</td></tr>)}</tbody>
          </table>
          <h3>Final metrics</h3>
          <table className="kv">
            <tbody>{Object.entries(run.summary).map(([k, v]) => <tr key={k}><td className="mono muted">{k}</td><td className="mono">{fmtNum(v)}</td></tr>)}</tbody>
          </table>
          {!Object.keys(run.summary).length && <p className="muted small">Available when the run finishes.</p>}
          <h3>Artifacts</h3>
          {artifacts.map((a) => (
            <div key={a.id} className="artifact">
              <div><b>{a.name}</b> <span className="chip">{a.kind}</span><div className="muted small mono">sha256 {a.sha256.slice(0, 16)}… · {fmtBytes(a.size_bytes)}</div></div>
              <button className="btn small" onClick={() => downloadArtifact(run.id, a)}>Download</button>
            </div>
          ))}
          {!artifacts.length && <p className="muted small">None yet.</p>}
        </section>
        <section className="panel">
          <h3>Timeline</h3>
          <ul className="timeline">
            {events.map((e) => <li key={e.id} className={`ev-${e.kind}`}><span className="muted small">{new Date(e.ts.endsWith('Z') ? e.ts : e.ts + 'Z').toLocaleTimeString()}</span> {e.message}</li>)}
          </ul>
        </section>
      </div>

      <section className="panel">
        <div className="panel-head"><h3>Logs</h3>{live && <span className="live">● live</span>}</div>
        <pre className="logs" ref={logRef}>{logs ?? 'Loading…'}</pre>
      </section>
    </div>
  )
}
