import { useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Link, useNavigate, useParams } from 'react-router-dom'
import AnalysisPanel from '../components/AnalysisPanel'
import LaunchPanel from '../components/LaunchPanel'
import StatusBadge from '../components/StatusBadge'
import { ACTIVE, fmtAgo, fmtDuration, fmtNum } from '../format'
import { selectCan } from '../store/authSlice'
import { fetchAnalyses, fetchExperiment, fetchExperimentRuns } from '../store/experimentsSlice'
import { setSelected, toggleSelected } from '../store/runsSlice'
import { usePoll } from '../usePoll'

const FILTERS = ['all', 'active', 'succeeded', 'failed']

export default function ExperimentDetail() {
  const { id } = useParams()
  const expId = Number(id)
  const dispatch = useDispatch()
  const nav = useNavigate()
  const exp = useSelector((s) => s.experiments.byId[expId])
  const runs = useSelector((s) => s.experiments.runsByExp[expId]) || []
  const selected = useSelector((s) => s.runs.selected)
  const canLaunch = useSelector(selectCan('researcher'))
  const [launch, setLaunch] = useState(false)
  const [filter, setFilter] = useState('all')
  const anyActive = runs.some((r) => ACTIVE.has(r.status))

  usePoll(() => { dispatch(fetchExperiment(expId)); dispatch(fetchExperimentRuns(expId)) }, anyActive ? 1500 : 5000, [expId])
  usePoll(() => dispatch(fetchAnalyses(expId)), null, [expId])

  if (!exp) return <div className="empty">Loading…</div>
  const pm = exp.primary_metric
  // Show hyperparameters that differ between runs; the most widely set ones (sweep axes) first.
  const prevalence = (k) => runs.filter((r) => k in r.config).length
  const cfgKeys = [...new Set(runs.flatMap((r) => Object.keys(r.config)))]
    .filter((k) => new Set(runs.map((r) => JSON.stringify(r.config[k]))).size > 1)
    .sort((a, b) => prevalence(b) - prevalence(a) || a.localeCompare(b)).slice(0, 5)
  const shown = runs.filter((r) => filter === 'all' || (filter === 'active' ? ACTIVE.has(r.status)
    : filter === 'failed' ? ['failed', 'stalled'].includes(r.status) : r.status === filter))
  const selHere = selected.filter((x) => runs.some((r) => r.id === x))

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="crumbs"><Link to="/experiments">Experiments</Link> /</div>
          <h1>{exp.name}</h1>
          <p className="muted">{exp.description} <code>{exp.entrypoint}</code> · optimising <code>{pm}</code> ({exp.metric_goal})</p>
        </div>
        <div className="row">
          <button className="btn" disabled={selHere.length < 2} onClick={() => nav(`/compare?ids=${selHere.join(',')}`)}>
            Compare {selHere.length || ''}
          </button>
          {canLaunch && <button className="btn primary" onClick={() => setLaunch(true)}>▶ Launch</button>}
        </div>
      </header>

      <AnalysisPanel experimentId={expId} selected={selHere} />

      <section className="panel">
        <div className="panel-head">
          <h3>Runs</h3>
          <div className="seg small">
            {FILTERS.map((f) => <button key={f} className={filter === f ? 'on' : ''} onClick={() => setFilter(f)}>{f}</button>)}
          </div>
        </div>
        <div className="scroll-x">
        <table className="table">
          <thead>
            <tr>
              <th><input type="checkbox" aria-label="select all" checked={shown.length > 0 && shown.every((r) => selected.includes(r.id))}
                onChange={(e) => dispatch(setSelected(e.target.checked ? shown.map((r) => r.id).slice(0, 12) : []))} /></th>
              <th>Run</th><th>Status</th>{cfgKeys.map((k) => <th key={k} className="mono">{k}</th>)}
              <th>{pm}</th><th>Progress</th><th>Duration</th><th>Created</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.id} className={exp.best_run_id === r.id ? 'best' : ''}>
                <td><input type="checkbox" checked={selected.includes(r.id)} onChange={() => dispatch(toggleSelected(r.id))} aria-label={`select run ${r.id}`} /></td>
                <td><Link to={`/runs/${r.id}`}>#{r.id}</Link> <span className="muted small">{r.name}</span>{exp.best_run_id === r.id && <span className="chip best">best</span>}</td>
                <td><StatusBadge status={r.status} />{r.attempt > 0 && <span className="muted small"> ×{r.attempt + 1}</span>}</td>
                {cfgKeys.map((k) => <td key={k} className="mono">{JSON.stringify(r.config[k])}</td>)}
                <td className="mono">{fmtNum(r.summary?.[pm])}</td>
                <td><div className="meter thin"><div style={{ width: `${r.progress * 100}%` }} /></div></td>
                <td>{fmtDuration(r.duration_s)}</td>
                <td className="muted">{fmtAgo(r.created_at)}</td>
              </tr>
            ))}
            {!shown.length && <tr><td colSpan={8 + cfgKeys.length} className="empty small">No runs{filter !== 'all' ? ` (${filter})` : ''}.</td></tr>}
          </tbody>
        </table>
        </div>
      </section>
      {launch && <LaunchPanel experiment={exp} onClose={() => setLaunch(false)} onLaunched={() => dispatch(fetchExperimentRuns(expId))} />}
    </div>
  )
}
