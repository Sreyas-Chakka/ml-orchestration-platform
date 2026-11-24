import { useEffect } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Navigate, NavLink, Route, Routes } from 'react-router-dom'
import Compare from './pages/Compare'
import ExperimentDetail from './pages/ExperimentDetail'
import Experiments from './pages/Experiments'
import Login from './pages/Login'
import Overview from './pages/Overview'
import RunDetail from './pages/RunDetail'
import Users from './pages/Users'
import { loadMe, logout, selectUser } from './store/authSlice'

export default function App() {
  const dispatch = useDispatch()
  const { status } = useSelector((s) => s.auth)
  const user = useSelector(selectUser)
  const selected = useSelector((s) => s.runs.selected)

  useEffect(() => {
    if (status === 'checking') dispatch(loadMe())
    const onLogout = () => dispatch(logout())
    window.addEventListener('mlops:logout', onLogout)
    return () => window.removeEventListener('mlops:logout', onLogout)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (status === 'checking') return <div className="empty">Loading…</div>
  if (!user) return <Login />

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="logo" /> Orchestrator</div>
        <nav>
          <NavLink to="/" end>Overview</NavLink>
          <NavLink to="/experiments">Experiments</NavLink>
          <NavLink to={`/compare${selected.length ? `?ids=${selected.join(',')}` : ''}`}>
            Compare {selected.length > 0 && <span className="count">{selected.length}</span>}
          </NavLink>
          {user.role === 'admin' && <NavLink to="/users">Users</NavLink>}
        </nav>
        <div className="side-foot">
          <a href="http://localhost:3000" target="_blank" rel="noreferrer" className="muted small">Grafana ↗</a>
          <div className="me">
            <div className="avatar">{(user.name || user.email)[0].toUpperCase()}</div>
            <div><div className="small">{user.name || user.email}</div><div className={`role role-${user.role}`}>{user.role}</div></div>
          </div>
          <button className="btn ghost small wide" onClick={() => dispatch(logout())}>Sign out</button>
        </div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/experiments" element={<Experiments />} />
          <Route path="/experiments/:id" element={<ExperimentDetail />} />
          <Route path="/runs/:id" element={<RunDetail />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/users" element={user.role === 'admin' ? <Users /> : <Navigate to="/" />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
    </div>
  )
}
