import { useMemo, useState } from 'react'
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, Legend, CartesianGrid, BarChart, Bar, Cell } from 'recharts'
import { Card, Empty, Notice } from '../components/ui'
import { ago } from '../lib/format'

const tip = { contentStyle: { background: '#0f172a', border: '1px solid #334155' } }
const NAMES = { J1: 'HSR Layout', J2: 'Silk Board Jn', J3: 'BTM Layout', J4: 'Madiwala' }

export default function Twin({ d }) {
  const [idx, setIdx] = useState(0)
  const [node, setNode] = useState('J2')
  const run = d.runs[idx]

  const curves = useMemo(() => {
    const t = run?.details?.timeline
    if (!t) return []
    const b = t.baseline?.[node] || [], o = t.optimised?.[node] || [], th = t.threshold?.[node] || []
    return b.map((p, i) => ({ minute: p[0], 'Today (no control)': p[2], 'Simple threshold sensor': th[i]?.[2] ?? 0, 'AquaGrid optimised': o[i]?.[2] ?? 0 }))
  }, [run, node])

  if (!run) return <Card wide title="Digital twin"><Empty>No twin runs yet. Start brain.py and press “Run twin forecast” in the Control Room.</Empty></Card>

  const compare = [
    { name: 'Today', v: run.flood_m3_baseline, c: '#dc2626' },
    { name: 'Threshold', v: run.flood_m3_threshold, c: '#f97316' },
    { name: 'AquaGrid', v: run.flood_m3_optimised, c: '#22c55e' },
  ]
  const openAt = run.details?.open_at || {}
  const gates = run.details?.gates || { OR1: 'J2', OR2: 'J3' }
  const speed = run.details?.speed || 1

  return (
    <div className="grid">
      <Card wide title="Digital twin (EPA SWMM)" sub={`${run.scenario} · ${run.rain_total_mm} mm rain · ${ago(run.created_at)}`}
        actions={<select value={idx} onChange={(e) => setIdx(+e.target.value)} aria-label="Choose run">
          {d.runs.map((r, i) => <option key={r.id} value={i}>Run #{r.id} · {r.scenario}</option>)}
        </select>}>
        <Notice kind="warn">{run.details?.assumptions || 'Illustrative starter model — not calibrated to real Bengaluru drains. Results are simulations.'}</Notice>
        <p className="headline">Modelled flood water on roads: <b>{run.flood_m3_baseline} m³</b> → <b>{run.flood_m3_optimised} m³</b> (−{run.reduction_pct}%) · captured for recharge {run.captured_m3} m³</p>
        <div className="row">
          <label>Junction: <select value={node} onChange={(e) => setNode(e.target.value)}>
            {Object.entries(NAMES).map(([k, v]) => <option key={k} value={k}>{v} ({k})</option>)}
          </select></label>
        </div>
        <div className="twin">
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={curves}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="minute" stroke="#94a3b8" unit=" min" /><YAxis stroke="#94a3b8" unit=" L/s" />
              <Tooltip {...tip} /><Legend />
              <Line dataKey="Today (no control)" stroke="#dc2626" dot={false} strokeWidth={2} />
              <Line dataKey="Simple threshold sensor" stroke="#f97316" dot={false} strokeWidth={2} />
              <Line dataKey="AquaGrid optimised" stroke="#22c55e" dot={false} strokeWidth={3} />
            </LineChart>
          </ResponsiveContainer>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={compare}>
              <XAxis dataKey="name" stroke="#94a3b8" /><YAxis stroke="#94a3b8" unit=" m³" />
              <Tooltip {...tip} />
              <Bar dataKey="v" name="Total flood volume">{compare.map((c) => <Cell key={c.name} fill={c.c} />)}</Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card title="Gate-operation plan" sub={speed > 1 ? `demo time: 1 s = ${speed / 60} sim min` : 'real time'}>
        <table>
          <thead><tr><th>Gate</th><th>Drains</th><th>Plan</th></tr></thead>
          <tbody>{Object.entries(gates).map(([g, n]) => (
            <tr key={g}><td>{g}</td><td>{NAMES[n] || n}</td>
              <td>{openAt[g] == null || openAt[g] >= 9999 ? 'Keep closed (opening does not reduce flooding)' : `Open at minute ${openAt[g]}`}</td></tr>
          ))}</tbody>
        </table>
        <p className="muted small">Before release the real node holds capacity (threshold 85 %), at release it switches to 25 %.</p>
      </Card>

      <Card title="Recent runs">
        <table>
          <thead><tr><th>#</th><th>Scenario</th><th>Today</th><th>AquaGrid</th><th>Cut</th></tr></thead>
          <tbody>{d.runs.map((r) => (
            <tr key={r.id}><td>{r.id}</td><td>{r.scenario}</td><td>{r.flood_m3_baseline}</td><td>{r.flood_m3_optimised}</td><td>{r.reduction_pct}%</td></tr>
          ))}</tbody>
        </table>
      </Card>
    </div>
  )
}
