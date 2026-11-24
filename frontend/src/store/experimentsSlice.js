import { createAsyncThunk, createSlice } from '@reduxjs/toolkit'
import { api } from '../api'

export const fetchExperiments = createAsyncThunk('experiments/fetch', () => api('/api/experiments'))
export const fetchExperiment = createAsyncThunk('experiments/fetchOne', (id) => api(`/api/experiments/${id}`))
export const createExperiment = createAsyncThunk('experiments/create', (body) =>
  api('/api/experiments', { method: 'POST', body }))
export const fetchExperimentRuns = createAsyncThunk('experiments/runs', async (id) => ({
  id, runs: await api(`/api/experiments/${id}/runs`),
}))
export const fetchAnalyses = createAsyncThunk('experiments/analyses', async (id) => ({
  id, analyses: await api(`/api/experiments/${id}/analyses`),
}))
export const runAnalysis = createAsyncThunk('experiments/analyze', async ({ id, runIds }) => ({
  id, analysis: await api(`/api/experiments/${id}/analyze`, { method: 'POST', body: { run_ids: runIds?.length ? runIds : null } }),
}))

const slice = createSlice({
  name: 'experiments',
  initialState: { byId: {}, order: [], runsByExp: {}, analysesByExp: {}, analyzing: false, analyzeError: null, loaded: false },
  reducers: {},
  extraReducers: (b) => {
    b.addCase(fetchExperiments.fulfilled, (s, a) => {
      s.order = a.payload.map((e) => e.id)
      a.payload.forEach((e) => { s.byId[e.id] = e })
      s.loaded = true
    })
      .addCase(fetchExperiment.fulfilled, (s, a) => { s.byId[a.payload.id] = a.payload })
      .addCase(createExperiment.fulfilled, (s, a) => {
        s.byId[a.payload.id] = a.payload
        s.order.unshift(a.payload.id)
      })
      .addCase(fetchExperimentRuns.fulfilled, (s, a) => { s.runsByExp[a.payload.id] = a.payload.runs })
      .addCase(fetchAnalyses.fulfilled, (s, a) => { s.analysesByExp[a.payload.id] = a.payload.analyses })
      .addCase(runAnalysis.pending, (s) => { s.analyzing = true; s.analyzeError = null })
      .addCase(runAnalysis.fulfilled, (s, a) => {
        s.analyzing = false
        s.analysesByExp[a.payload.id] = [a.payload.analysis, ...(s.analysesByExp[a.payload.id] || [])]
      })
      .addCase(runAnalysis.rejected, (s, a) => { s.analyzing = false; s.analyzeError = a.error.message })
  },
})

export default slice.reducer
