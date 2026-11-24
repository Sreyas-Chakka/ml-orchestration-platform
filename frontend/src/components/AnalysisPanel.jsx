import { useDispatch, useSelector } from 'react-redux'
import { Link } from 'react-router-dom'
import { fmtAgo } from '../format'
import { selectCan } from '../store/authSlice'
import { runAnalysis } from '../store/experimentsSlice'

export default function AnalysisPanel({ experimentId, selected }) {
  const dispatch = useDispatch()
  const canRun = useSelector(selectCan('researcher'))
  const analyses = useSelector((s) => s.experiments.analysesByExp[experimentId]) || []
  const { analyzing, analyzeError } = useSelector((s) => s.experiments)
  const a = analyses[0]

  return (
    <section className="panel analysis">
      <div className="panel-head">
        <h3>
          <span className="spark">✦</span> Run analyst
          {a && <span className={`chip ${a.source}`}>{a.source === 'claude' ? a.model || 'Claude' : 'rule-based'}</span>}
        </h3>
        {canRun && (
          <button className="btn" disabled={analyzing} onClick={() => dispatch(runAnalysis({ id: experimentId, runIds: selected }))}>
            {analyzing ? 'Analysing…' : selected.length ? `Analyse ${selected.length} selected` : 'Analyse all runs'}
          </button>
        )}
      </div>
      {analyzeError && <div className="error">{analyzeError}</div>}
      {!a ? (
        <p className="muted">Summarises results across runs, picks the best configuration and flags anomalies such as divergence, overfitting, stalls and crashes.</p>
      ) : (
        <>
          <p className="summary">{a.summary}</p>
          <div className="analysis-meta muted">
            {a.run_ids.length} runs · {fmtAgo(a.created_at)}
            {a.best_run_id && <> · best: <Link to={`/runs/${a.best_run_id}`}>#{a.best_run_id}</Link></>}
          </div>
          {a.anomalies.length > 0 && (
            <ul className="anomalies">
              {a.anomalies.map((x, i) => (
                <li key={i} className={`sev-${x.severity}`}>
                  <span className="sev">{x.severity}</span>
                  <div>
                    <Link to={`/runs/${x.run_id}`}>#{x.run_id}</Link> {x.issue}
                    <div className="muted">→ {x.recommendation}</div>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {a.recommendations.length > 0 && (
            <>
              <div className="label">Next steps</div>
              <ol className="recs">{a.recommendations.map((r, i) => <li key={i}>{r}</li>)}</ol>
            </>
          )}
        </>
      )}
    </section>
  )
}
