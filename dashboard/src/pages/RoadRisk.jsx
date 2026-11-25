import { useMemo, useState } from 'react'
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine } from 'recharts'
import { Card, Empty, Badge, Bar, Notice } from '../components/ui'
import { RISK_COLOUR, ago } from '../lib/format'

export default function RoadRisk({ d }) {
  const roads = [...d.roads].sort((a, b) => (b.risk ?? 0) - (a.risk ?? 0))
  const [seg, setSeg] = useState('J2')
  const trend = useMemo(() => d.riskHistory.filter((h) => h.segment === seg).map((h) => ({
    t: new Date(h.created_at).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }),
    risk: h.risk,
  })), [d.riskHistory, seg])
  const noFlood = roads.some((r) => r.flood_available === false)

  return (
    <div className="grid">
      <Card wide title="Road risk ranking" sub="risk = 0.6 × flood exposure + 0.4 × pothole density">
        {noFlood && <Notice kind="warn">Some roads have no flood forecast from the last 24 h. Their score uses potholes only and may be under-estimated — this is not treated as zero flood risk.</Notice>}
        {roads.length ? (
          <div className="tablewrap"><table>
            <thead><tr><th>#</th><th>Road</th><th>Risk</th><th>Flood part (×0.6)</th><th>Pothole part (×0.4)</th><th>Potholes</th><th>Why</th><th>Updated</th></tr></thead>
            <tbody>{roads.map((r, i) => (
              <tr key={r.segment}>
                <td>{i + 1}</td><td>{r.name}</td>
                <td><Badge colour={RISK_COLOUR[r.label]}>{r.label}</Badge> {(r.risk ?? 0).toFixed(2)}</td>
                <td>{r.flood_available === false ? <span className="muted">no forecast</span> : <><Bar value={0.6 * (r.flood_score || 0)} colour="#38bdf8" /><small>{(0.6 * (r.flood_score || 0)).toFixed(2)}</small></>}</td>
                <td><Bar value={0.4 * (r.pothole_score || 0)} colour="#f97316" /><small>{(0.4 * (r.pothole_score || 0)).toFixed(2)}</small></td>
                <td>{r.pothole_count ?? 0}</td>
                <td className="small">{r.explanation || '—'}</td>
                <td>{ago(r.updated_at)}</td>
              </tr>
            ))}</tbody>
          </table></div>
        ) : <Empty>No risk records yet — run <code>python road_risk.py</code>.</Empty>}
        <p className="muted small">Thresholds: LOW &lt; 0.20 ≤ MEDIUM &lt; 0.45 ≤ HIGH &lt; 0.70 ≤ CRITICAL. Normalisation: 300 m³ predicted flooding = full flood exposure; 10 severity-weighted potholes in 30 days = full pothole density. Starting values, to be tuned with repair records.</p>
      </Card>

      <Card wide title="Risk trend" actions={<select value={seg} onChange={(e) => setSeg(e.target.value)} aria-label="Road">
        {roads.map((r) => <option key={r.segment} value={r.segment}>{r.name}</option>)}
      </select>}>
        {trend.length > 1 ? (
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={trend}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="t" stroke="#94a3b8" minTickGap={40} /><YAxis domain={[0, 1]} stroke="#94a3b8" />
              <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155' }} />
              <ReferenceLine y={0.7} stroke="#dc2626" strokeDasharray="4 4" />
              <ReferenceLine y={0.45} stroke="#f97316" strokeDasharray="4 4" />
              <ReferenceLine y={0.2} stroke="#eab308" strokeDasharray="4 4" />
              <Line dataKey="risk" stroke="#38bdf8" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : <Empty>History builds up while road_risk.py runs (a point every 10 min or on every label change).</Empty>}
      </Card>
    </div>
  )
}
