import { useEffect } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Link, useSearchParams } from 'react-router-dom'
import MetricChart from '../components/MetricChart'
import StatusBadge from '../components/StatusBadge'
import { fmtDuration, fmtNum, RUN_COLORS } from '../format'
import { fetchCompare } from '../store/runsSlice'

export default function Compare() {
  const [params] = useSearchParams()
  const ids = (params.get('ids') || '').split(',').map(Number).filter(Boolean)
  const dispatch = useDispatch()
  const data = useSelector((s) => s.runs.compare)
  const key = ids.join(',')
  useEffect(() => { if (ids.length) dispatch(fetchCompare(ids)) }, [key]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!ids.length) return <div className="page"><h1>Compare</h1><p className="muted">Select two or more runs on an experiment page.</p></div>
  if (!data) return <div className="empty">Loading…</div>
  const runs = [...data.runs].sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id))
  const summaryKeys = [...new Set(runs.flatMap((r) => Object.keys(r.summary)))]

  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Compare {runs.length} runs</h1>
          <p className="muted">Differing hyperparameters are highlighted.</p></div>
      </header>
      <div className="charts">
        {data.metric_keys.map((k) => (
          <MetricChart key={k} title={k} series={runs.map((r) => ({ id: r.id, label: `#${r.id}`, points: data.series[r.id]?.[k] || [] }))} />
        ))}
      </div>
      <section className="panel scroll-x">
        <table className="table compare">
          <thead>
            <tr><th />{runs.map((r, i) => <th key={r.id}><span className="swatch" style={{ background: RUN_COLORS[i % RUN_COLORS.length] }} /><Link to={`/runs/${r.id}`}>#{r.id}</Link></th>)}</tr>
          </thead>
          <tbody>
            <tr><td className="muted">status</td>{runs.map((r) => <td key={r.id}><StatusBadge status={r.status} /></td>)}</tr>
            <tr><td className="muted">duration</td>{runs.map((r) => <td key={r.id}>{fmtDuration(r.duration_s)}</td>)}</tr>
            <tr className="section"><td colSpan={runs.length + 1}>Config</td></tr>
            {data.config_keys.map((k) => (
              <tr key={k} className={data.differing_config_keys.includes(k) ? 'diff' : ''}>
                <td className="mono muted">{k}</td>{runs.map((r) => <td key={r.id} className="mono">{JSON.stringify(r.config[k])}</td>)}
              </tr>
            ))}
            <tr className="section"><td colSpan={runs.length + 1}>Results</td></tr>
            {summaryKeys.map((k) => {
              const vals = runs.map((r) => r.summary[k]).filter((v) => v != null)
              const best = k.includes('loss') ? Math.min(...vals) : Math.max(...vals)
              return (
                <tr key={k}><td className="mono muted">{k}</td>
                  {runs.map((r) => <td key={r.id} className={`mono ${r.summary[k] === best && vals.length > 1 ? 'win' : ''}`}>{fmtNum(r.summary[k])}</td>)}</tr>
              )
            })}
          </tbody>
        </table>
      </section>
    </div>
  )
}
