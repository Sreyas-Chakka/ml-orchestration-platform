import { configureStore } from '@reduxjs/toolkit'
import auth from './authSlice'
import experiments from './experimentsSlice'
import runs from './runsSlice'

export const store = configureStore({ reducer: { auth, experiments, runs } })
