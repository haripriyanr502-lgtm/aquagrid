import { ResponsiveContainer, LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, Legend, CartesianGrid } from 'recharts'
import { Card, Empty, SimTag, RealTag, Notice } from '../components/ui'
import { REAL, REASON_TEXT, ago, isOnline, isSimulated } from '../lib/format'

const tip = { contentStyle: { background: '#0f172a', border: '1px solid #334155' } }

export default function Flood({ d }) {
  const run = d.runs[0]
  const rain = (run?.details?.rain || []).map((v, i) => ({ t: `${Math.floor(i * 15 / 60)}:${String((i * 15) % 60).padStart(2, '0')}`, mm: v }))
  const realNode = d.nodes.find((n) => n.id === REAL)
  const lastReal = d.latest[REAL]
  const nodes = [...d.nodes].sort((a, b) => (d.latest[b.id]?.level_pct ?? -1) - (d.latest[a.id]?.level_pct ?? -1))
  const risk = run?.details?.risk || {}

  return (
    <div className="grid">
      <Card title="Rainfall used by the latest forecast" sub={run ? `${run.details?.rain_source || run.scenario} · ${ago(run.created_at)}` : ''}>
        {rain.length ? (
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={rain}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="t" stroke="#94a3b8" /><YAxis stroke="#94a3b8" unit=" mm/h" />
              <Tooltip {...tip} /><Bar dataKey="mm" name="Rain intensity" fill="#38bdf8" />
            </BarChart>
          </ResponsiveContainer>
        ) : <Empty>No rainfall series yet (brain.py fetches Open-Meteo every 10 min).</Empty>}
      </Card>

      <Card title="Flood predictions per road" sub="digital twin, illustrative">
        {Object.keys(risk).length ? (
          <table>
            <thead><tr><th>Road</th><th>Floods in</th><th>Today</th><th>With AquaGrid</th></tr></thead>
            <tbody>{Object.entries(risk).map(([k, r]) => (
              <tr key={k}><td>{r.name}</td><td>{r.floods_in_min != null ? `${r.floods_in_min} min` : 'no flood'}</td>
                <td>{r.flood_m3} m³</td><td>{r.flood_m3_optimised ?? r.flood_m3_drainx ?? '—'} m³</td></tr>
            ))}</tbody>
          </table>
        ) : <Empty>No prediction yet.</Empty>}
      </Card>

      <Card wide title="Water level — Silk Board node" sub={lastReal?.is_simulated ? 'bridge in --simulate mode' : 'real hardware'}>
        {lastReal?.is_simulated && <Notice kind="warn">These readings come from the bridge's software model (no Arduino attached). They are not real measurements.</Notice>}
        {d.history.length ? (
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={d.history.map((r) => ({
              t: new Date(r.created_at).toLocaleTimeString('en-IN', { minute: '2-digit', second: '2-digit' }),
              level: r.level_pct, pit: r.pit_pct, gate: r.gate_open ? 100 : 0,
            }))}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="t" stroke="#94a3b8" minTickGap={30} /><YAxis domain={[0, 100]} stroke="#94a3b8" unit="%" />
              <Tooltip {...tip} /><Legend />
              <Line dataKey="level" name="Drain level" stroke="#38bdf8" dot={false} strokeWidth={2} isAnimationActive={false} />
              <Line dataKey="pit" name="Recharge pit" stroke="#22c55e" dot={false} strokeWidth={2} isAnimationActive={false} />
              <Line dataKey="gate" name="Gate open" stroke="#a78bfa" dot={false} strokeDasharray="4 4" type="stepAfter" isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : <Empty>{realNode ? 'No readings yet — is bridge.py running?' : 'Node SS-01 not registered — run simulator.py once.'}</Empty>}
      </Card>

      <Card wide title="Node status" sub="sorted by water level">
        <div className="tablewrap">
          <table>
            <thead><tr><th>Node</th><th>Type</th><th>Level</th><th>Pit</th><th>Gate</th><th>State</th><th>Quality</th><th>Last seen</th></tr></thead>
            <tbody>{nodes.map((n) => {
              const r = d.latest[n.id]
              return (
                <tr key={n.id} className={!isOnline(r) ? 'stale' : ''}>
                  <td>{n.name}</td><td>{isSimulated(n, r) ? <SimTag /> : <RealTag />}</td>
                  <td>{r?.level_pct ?? '—'}%</td><td>{r?.pit_pct ?? '—'}%</td><td>{r?.gate_open ? 'OPEN' : 'shut'}</td>
                  <td>{REASON_TEXT[r?.reason] || r?.reason || '—'}</td><td>{r ? (r.quality_ok ? 'clean' : 'dirty / n.a.') : '—'}</td>
                  <td>{ago(r?.created_at)}</td>
                </tr>
              )
            })}</tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
