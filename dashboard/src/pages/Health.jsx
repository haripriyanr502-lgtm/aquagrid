import { Card, Badge, Empty, Notice } from '../components/ui'
import { ago, serviceAlive } from '../lib/format'

const SERVICES = [
  ['bridge', 'Arduino bridge', 'python bridge.py'],
  ['simulator', 'City simulator', 'python simulator.py'],
  ['brain', 'Digital twin brain', 'python brain.py'],
  ['alerts', 'Telegram alerts', 'python alerts.py'],
  ['road_risk', 'Road risk', 'python road_risk.py'],
  ['repair_priority', 'Repair priority', 'python repair_priority.py'],
  ['drainx', 'DrainX AI worker', 'python pothole_detect.py --worker'],
]

function state(s) {
  if (!s) return ['never started', '#64748b']
  if (!serviceAlive(s, 90)) return ['offline', '#dc2626']
  if (s.status === 'error') return ['error', '#dc2626']
  if (s.status === 'warning' || s.status === 'offline') return [s.status, '#f97316']
  return ['ok', '#16a34a']
}

export default function Health({ d }) {
  const bridge = d.services.bridge?.detail || {}
  const ai = d.services.drainx?.detail || {}
  return (
    <div className="grid">
      <Card title="Connections">
        <table><tbody>
          <tr><td>Database (Supabase)</td><td>{d.dbOk ? <Badge colour="#16a34a">connected</Badge> : d.dbOk === false ? <Badge colour="#dc2626">error</Badge> : '…'}</td></tr>
          <tr><td>Realtime</td><td><Badge colour={d.realtime === 'live' ? '#16a34a' : '#f97316'}>{d.realtime}</Badge></td></tr>
          <tr><td>Hardware (SS-01)</td><td>{bridge.hardware ? <Badge colour={bridge.simulated ? '#f97316' : bridge.hardware === 'connected' ? '#16a34a' : '#dc2626'}>{bridge.hardware}</Badge> : '—'}</td></tr>
          <tr><td>AI model</td><td>{ai.model_loaded ? <Badge colour="#16a34a">{ai.model_version}</Badge> : ai.model_path ? <Badge colour="#dc2626">missing</Badge> : '—'}</td></tr>
          <tr><td>Model evaluated</td><td>{ai.metrics ? `mAP50 ${ai.metrics.map50}` : 'not yet'}</td></tr>
          <tr><td>Signed in</td><td>{d.session ? d.session.user.email : 'no (read-only)'}</td></tr>
        </tbody></table>
      </Card>
      <Card title="Data problems">
        {d.problems.length ? d.problems.map((p, i) => <Notice key={i} kind="error">{p}</Notice>) : <p>No query errors.</p>}
      </Card>
      <Card wide title="Backend services" sub="each service reports every 10–30 s">
        <table>
          <thead><tr><th>Service</th><th>Status</th><th>Last seen</th><th>Detail</th><th>Start with</th></tr></thead>
          <tbody>{SERVICES.map(([k, name, cmd]) => {
            const s = d.services[k]
            const [label, colour] = state(s)
            const detail = s?.detail ? Object.entries(s.detail).filter(([, v]) => v !== null && typeof v !== 'object').slice(0, 5)
              .map(([a, b]) => `${a}: ${b}`).join(' · ') : ''
            return (
              <tr key={k}><td>{name}</td><td><Badge colour={colour}>{label}</Badge></td><td>{ago(s?.last_seen)}</td>
                <td className="small">{detail || '—'}</td><td><code>{cmd}</code></td></tr>
            )
          })}</tbody>
        </table>
        {!Object.keys(d.services).length && <Empty>No service has reported yet. Run migration 002, then start the scripts.</Empty>}
      </Card>
    </div>
  )
}
