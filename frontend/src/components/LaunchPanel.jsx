import { useState } from 'react'
import { useDispatch } from 'react-redux'
import { parseList } from '../format'
import { launchRun, launchSweep } from '../store/runsSlice'
import Modal from './Modal'

const PARAMS = [
  ['learning_rate', '0.05', '0.01, 0.05, 0.2'],
  ['hidden_units', '32', '8, 32'],
  ['epochs', '30', ''],
  ['batch_size', '64', ''],
  ['weight_decay', '0', '0, 0.001'],
]

function toConfig(values) {
  const out = {}
  Object.entries(values).forEach(([k, v]) => {
    if (v === '' || v == null) return
    const n = Number(v)
    out[k] = Number.isNaN(n) ? v : n
  })
  return out
}

export default function LaunchPanel({ experiment, onClose, onLaunched }) {
  const dispatch = useDispatch()
  const [mode, setMode] = useState('single')
  const [single, setSingle] = useState(Object.fromEntries(PARAMS.map(([k]) => [k, experiment.base_config?.[k] ?? ''])))
  const [grid, setGrid] = useState(Object.fromEntries(PARAMS.map(([k, , g]) => [k, g])))
  const [extra, setExtra] = useState('')
  const [priority, setPriority] = useState(0)
  const [retries, setRetries] = useState(0)
  const [cpu, setCpu] = useState('500m')
  const [memory, setMemory] = useState('512Mi')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setError(null)
    let extraCfg = {}
    try {
      extraCfg = extra.trim() ? JSON.parse(extra) : {}
    } catch {
      setError('Extra config must be valid JSON')
      return
    }
    const resources = { cpu, memory }
    setBusy(true)
    try {
      if (mode === 'single') {
        await dispatch(launchRun({ expId: experiment.id, body: {
          config: { ...toConfig(single), ...extraCfg }, priority: Number(priority), max_retries: Number(retries), resources,
        } })).unwrap()
      } else {
        const g = {}
        Object.entries(grid).forEach(([k, v]) => { const vals = parseList(v); if (vals.length) g[k] = vals })
        if (!Object.keys(g).length) throw new Error('Add at least one swept parameter')
        await dispatch(launchSweep({ expId: experiment.id, body: { grid: g, base: extraCfg, priority: Number(priority), resources } })).unwrap()
      }
      onLaunched?.()
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const sweepSize = Object.values(grid).reduce((n, v) => n * Math.max(1, parseList(v).length), 1)

  return (
    <Modal title={`Launch on “${experiment.name}”`} onClose={onClose}>
      <form onSubmit={submit} className="form">
        <div className="seg">
          <button type="button" className={mode === 'single' ? 'on' : ''} onClick={() => setMode('single')}>Single run</button>
          <button type="button" className={mode === 'sweep' ? 'on' : ''} onClick={() => setMode('sweep')}>Grid sweep</button>
        </div>
        <div className="grid2">
          {PARAMS.map(([k]) => (
            <label key={k}>
              <span>{k}{mode === 'sweep' && <em> (comma-separated)</em>}</span>
              {mode === 'single'
                ? <input value={single[k]} onChange={(e) => setSingle({ ...single, [k]: e.target.value })} />
                : <input value={grid[k]} placeholder="leave blank to use default" onChange={(e) => setGrid({ ...grid, [k]: e.target.value })} />}
            </label>
          ))}
        </div>
        <label>
          <span>Extra config (JSON, merged into every run)</span>
          <input className="mono" value={extra} onChange={(e) => setExtra(e.target.value)} placeholder='{"seed": 1, "fail_at_epoch": 5}' />
        </label>
        <div className="grid4">
          <label><span>Priority</span><input type="number" min="-10" max="10" value={priority} onChange={(e) => setPriority(e.target.value)} /></label>
          <label><span>Max retries</span><input type="number" min="0" max="5" value={retries} disabled={mode === 'sweep'} onChange={(e) => setRetries(e.target.value)} /></label>
          <label><span>CPU request</span><input value={cpu} onChange={(e) => setCpu(e.target.value)} /></label>
          <label><span>Memory</span><input value={memory} onChange={(e) => setMemory(e.target.value)} /></label>
        </div>
        {error && <div className="error">{error}</div>}
        <div className="row end">
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy}>
            {busy ? 'Submitting…' : mode === 'single' ? 'Queue run' : `Queue ${sweepSize} runs`}
          </button>
        </div>
      </form>
    </Modal>
  )
}
