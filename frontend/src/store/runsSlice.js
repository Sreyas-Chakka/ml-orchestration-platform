import { createAsyncThunk, createSlice } from '@reduxjs/toolkit'
import { api } from '../api'

export const fetchRun = createAsyncThunk('runs/fetch', async (id) => {
  const [run, metrics, events, artifacts] = await Promise.all([
    api(`/api/runs/${id}`), api(`/api/runs/${id}/metrics`), api(`/api/runs/${id}/events`), api(`/api/runs/${id}/artifacts`),
  ])
  return { run, metrics, events, artifacts }
})
export const fetchLogs = createAsyncThunk('runs/logs', async (id) => ({ id, text: await api(`/api/runs/${id}/logs?tail=400`, { raw: true }) }))
export const fetchRecentRuns = createAsyncThunk('runs/recent', () => api('/api/runs?limit=50'))
export const fetchStats = createAsyncThunk('runs/stats', () => api('/api/stats'))
export const cancelRun = createAsyncThunk('runs/cancel', (id) => api(`/api/runs/${id}/cancel`, { method: 'POST' }))
export const retryRun = createAsyncThunk('runs/retry', (id) => api(`/api/runs/${id}/retry`, { method: 'POST' }))
export const launchRun = createAsyncThunk('runs/launch', ({ expId, body }) =>
  api(`/api/experiments/${expId}/runs`, { method: 'POST', body }))
export const launchSweep = createAsyncThunk('runs/sweep', ({ expId, body }) =>
  api(`/api/experiments/${expId}/sweeps`, { method: 'POST', body }))
export const fetchCompare = createAsyncThunk('runs/compare', (ids) => api(`/api/runs/compare?ids=${ids.join(',')}`))

const slice = createSlice({
  name: 'runs',
  initialState: { detail: {}, logs: {}, recent: [], stats: null, compare: null, selected: [] },
  reducers: {
    toggleSelected(s, a) {
      const id = a.payload
      s.selected = s.selected.includes(id) ? s.selected.filter((x) => x !== id) : [...s.selected, id].slice(-12)
    },
    setSelected(s, a) { s.selected = a.payload },
  },
  extraReducers: (b) => {
    b.addCase(fetchRun.fulfilled, (s, a) => { s.detail[a.payload.run.id] = a.payload })
      .addCase(fetchLogs.fulfilled, (s, a) => { s.logs[a.payload.id] = a.payload.text })
      .addCase(fetchRecentRuns.fulfilled, (s, a) => { s.recent = a.payload })
      .addCase(fetchStats.fulfilled, (s, a) => { s.stats = a.payload })
      .addCase(fetchCompare.fulfilled, (s, a) => { s.compare = a.payload })
      .addCase(cancelRun.fulfilled, (s, a) => { if (s.detail[a.payload.id]) s.detail[a.payload.id].run = a.payload })
      .addCase(retryRun.fulfilled, (s, a) => { if (s.detail[a.payload.id]) s.detail[a.payload.id].run = a.payload })
  },
})

export const { toggleSelected, setSelected } = slice.actions
export default slice.reducer
