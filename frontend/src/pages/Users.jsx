import { useEffect, useState } from 'react'
import { useSelector } from 'react-redux'
import { api } from '../api'
import { fmtAgo } from '../format'
import { selectUser } from '../store/authSlice'

export default function Users() {
  const me = useSelector(selectUser)
  const [users, setUsers] = useState([])
  const [f, setF] = useState({ email: '', name: '', password: '', role: 'researcher' })
  const [error, setError] = useState(null)
  const load = () => api('/api/auth/users').then(setUsers).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])

  async function add(e) {
    e.preventDefault()
    setError(null)
    try { await api('/api/auth/users', { method: 'POST', body: f }); setF({ email: '', name: '', password: '', role: 'researcher' }); load() } catch (err) { setError(err.message) }
  }
  async function setRole(id, role) {
    try { await api(`/api/auth/users/${id}`, { method: 'PATCH', body: { role } }); load() } catch (err) { setError(err.message) }
  }

  return (
    <div className="page">
      <header className="page-head"><h1>Users & roles</h1></header>
      <p className="muted">Viewers can read everything. Researchers can create experiments, launch, cancel and retry their own runs. Admins manage users and any run.</p>
      {error && <div className="error">{error}</div>}
      <section className="panel">
        <div className="scroll-x"><table className="table">
          <thead><tr><th>Email</th><th>Name</th><th>Role</th><th>Joined</th></tr></thead>
          <tbody>{users.map((u) => (
            <tr key={u.id}><td>{u.email}</td><td>{u.name}</td>
              <td><select value={u.role} disabled={u.id === me.id} onChange={(e) => setRole(u.id, e.target.value)}>
                <option>viewer</option><option>researcher</option><option>admin</option></select></td>
              <td className="muted">{fmtAgo(u.created_at)}</td></tr>
          ))}</tbody>
        </table></div>
      </section>
      <section className="panel">
        <h3>Add user</h3>
        <form className="form grid4" onSubmit={add}>
          <label><span>Email</span><input required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></label>
          <label><span>Name</span><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
          <label><span>Password</span><input required minLength={6} type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></label>
          <label><span>Role</span><select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}><option>viewer</option><option>researcher</option><option>admin</option></select></label>
          <div><button className="btn primary">Add</button></div>
        </form>
      </section>
    </div>
  )
}
