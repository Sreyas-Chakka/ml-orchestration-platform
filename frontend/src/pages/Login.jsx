import { useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { login } from '../store/authSlice'

const DEMO = [
  ['admin@mlops.local', 'admin123', 'admin'],
  ['researcher@mlops.local', 'research123', 'researcher'],
  ['viewer@mlops.local', 'viewer123', 'viewer'],
]

export default function Login() {
  const dispatch = useDispatch()
  const { error, status } = useSelector((s) => s.auth)
  const [email, setEmail] = useState('researcher@mlops.local')
  const [password, setPassword] = useState('research123')
  return (
    <div className="login-wrap">
      <form className="login" onSubmit={(e) => { e.preventDefault(); dispatch(login({ email, password })) }}>
        <div className="brand big"><span className="logo" /> Orchestrator</div>
        <p className="muted">Schedule, monitor and compare ML training runs.</p>
        <label><span>Email</span><input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" /></label>
        <label><span>Password</span><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
        {error && <div className="error">{error}</div>}
        <button className="btn primary wide" disabled={status === 'loading'}>{status === 'loading' ? 'Signing in…' : 'Sign in'}</button>
        <div className="demo">
          <div className="label">Demo accounts</div>
          {DEMO.map(([e, p, r]) => (
            <button type="button" key={e} className="btn ghost small" onClick={() => { setEmail(e); setPassword(p) }}>{r}</button>
          ))}
        </div>
      </form>
    </div>
  )
}
