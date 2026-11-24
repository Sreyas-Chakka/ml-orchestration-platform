import { useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Link, useNavigate } from 'react-router-dom'
import Modal from '../components/Modal'
import { fmtAgo, fmtNum } from '../format'
import { selectCan } from '../store/authSlice'
import { createExperiment, fetchExperiments } from '../store/experimentsSlice'
import { usePoll } from '../usePoll'

function NewExperiment({ onClose }) {
  const dispatch = useDispatch()
  const nav = useNavigate()
  const [f, setF] = useState({ name: '', description: '', entrypoint: 'mlp_classifier', primary_metric: 'val_accuracy', metric_goal: 'max', base: '{"epochs": 30, "epoch_sleep_s": 0.3}' })
  const [error, setError] = useState(null)
  async function submit(e) {
    e.preventDefault()
    try {
      const exp = await dispatch(createExperiment({
        name: f.name, description: f.description, entrypoint: f.entrypoint, primary_metric: f.primary_metric,
        metric_goal: f.metric_goal, base_config: f.base.trim() ? JSON.parse(f.base) : {},
      })).unwrap()
      nav(`/experiments/${exp.id}`)
    } catch (err) { setError(err.message) }
  }
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  return (
    <Modal title="New experiment" onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label><span>Name</span><input required value={f.name} onChange={set('name')} placeholder="spiral-mlp-baseline" /></label>
        <label><span>Description</span><input value={f.description} onChange={set('description')} /></label>
        <div className="grid3">
          <label><span>Entrypoint</span>
            <select value={f.entrypoint} onChange={set('entrypoint')}>
              <option value="mlp_classifier">mlp_classifier</option>
              <option value="logistic_regression">logistic_regression</option>
            </select>
          </label>
          <label><span>Primary metric</span><input value={f.primary_metric} onChange={set('primary_metric')} /></label>
          <label><span>Goal</span><select value={f.metric_goal} onChange={set('metric_goal')}><option>max</option><option>min</option></select></label>
        </div>
        <label><span>Base config (JSON)</span><input className="mono" value={f.base} onChange={set('base')} /></label>
        {error && <div className="error">{error}</div>}
        <div className="row end"><button type="button" className="btn ghost" onClick={onClose}>Cancel</button><button className="btn primary">Create</button></div>
      </form>
    </Modal>
  )
}

export default function Experiments() {
  const dispatch = useDispatch()
  const canCreate = useSelector(selectCan('researcher'))
  const { order, byId, loaded } = useSelector((s) => s.experiments)
  const [open, setOpen] = useState(false)
  usePoll(() => dispatch(fetchExperiments()), 4000)

  return (
    <div className="page">
      <header className="page-head">
        <h1>Experiments</h1>
        {canCreate && <button className="btn primary" onClick={() => setOpen(true)}>+ New experiment</button>}
      </header>
      <div className="cards">
        {order.map((id) => {
          const e = byId[id]
          const c = e.run_counts || {}
          const total = Object.values(c).reduce((a, b) => a + b, 0)
          return (
            <Link key={id} to={`/experiments/${id}`} className="card">
              <div className="card-top"><b>{e.name}</b><span className="muted small">{fmtAgo(e.created_at)}</span></div>
              <p className="muted small clamp">{e.description || e.entrypoint}</p>
              <div className="card-stats">
                <div><span className="label">runs</span>{total}</div>
                <div><span className="label">active</span>{(c.queued || 0) + (c.scheduled || 0) + (c.running || 0)}</div>
                <div><span className="label">failed</span>{(c.failed || 0) + (c.stalled || 0)}</div>
                <div><span className="label">best {e.primary_metric}</span>{fmtNum(e.best_value)}</div>
              </div>
            </Link>
          )
        })}
        {loaded && !order.length && <div className="empty">No experiments yet.</div>}
      </div>
      {open && <NewExperiment onClose={() => setOpen(false)} />}
    </div>
  )
}
