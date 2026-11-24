import { createAsyncThunk, createSlice } from '@reduxjs/toolkit'
import { api } from '../api'

export const login = createAsyncThunk('auth/login', async ({ email, password }) => {
  const res = await api('/api/auth/login', { method: 'POST', body: { email, password } })
  localStorage.setItem('mlops_token', res.access_token)
  return res.user
})

export const loadMe = createAsyncThunk('auth/me', () => api('/api/auth/me'))

const RANK = { viewer: 0, researcher: 1, admin: 2 }

const slice = createSlice({
  name: 'auth',
  initialState: { user: null, status: localStorage.getItem('mlops_token') ? 'checking' : 'anon', error: null },
  reducers: {
    logout(state) {
      localStorage.removeItem('mlops_token')
      state.user = null
      state.status = 'anon'
    },
  },
  extraReducers: (b) => {
    b.addCase(login.pending, (s) => { s.error = null; s.status = 'loading' })
      .addCase(login.fulfilled, (s, a) => { s.user = a.payload; s.status = 'authed' })
      .addCase(login.rejected, (s, a) => { s.error = a.error.message; s.status = 'anon' })
      .addCase(loadMe.fulfilled, (s, a) => { s.user = a.payload; s.status = 'authed' })
      .addCase(loadMe.rejected, (s) => { s.user = null; s.status = 'anon' })
  },
})

export const { logout } = slice.actions
export const selectUser = (s) => s.auth.user
export const selectCan = (min) => (s) => !!s.auth.user && RANK[s.auth.user.role] >= RANK[min]
export default slice.reducer
