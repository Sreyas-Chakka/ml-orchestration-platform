import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { RUN_COLORS } from '../format'

/**
 * series: [{ id, label, points: [[step, value], ...] }]
 * Merges all series onto a shared step axis so recharts can overlay them.
 */
export default function MetricChart({ title, series, height = 220 }) {
  const steps = new Map()
  series.forEach((s) => s.points.forEach(([step, v]) => {
    if (!steps.has(step)) steps.set(step, { step })
    steps.get(step)[`s${s.id}`] = v
  }))
  const data = [...steps.values()].sort((a, b) => a.step - b.step)
  return (
    <div className="chart-card">
      <div className="chart-title">{title}</div>
      {data.length === 0 ? (
        <div className="empty small">No data yet</div>
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="step" stroke="var(--muted)" fontSize={11} tickLine={false} />
            <YAxis stroke="var(--muted)" fontSize={11} tickLine={false} domain={['auto', 'auto']}
              tickFormatter={(v) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2))} />
            <Tooltip contentStyle={{ background: 'var(--panel-2)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }}
              formatter={(v) => (v == null ? 'NaN' : v.toFixed(4))} labelFormatter={(l) => `step ${l}`} />
            {series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
            {series.map((s, i) => (
              <Line key={s.id} type="monotone" dataKey={`s${s.id}`} name={s.label} stroke={RUN_COLORS[i % RUN_COLORS.length]}
                strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
