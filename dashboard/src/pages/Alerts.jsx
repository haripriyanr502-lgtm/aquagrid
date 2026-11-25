import { useState } from 'react'
import { Card, Empty, Badge } from '../components/ui'
import { SEV_COLOUR, ago, serviceAlive, time } from '../lib/format'

const KINDS = { pothole: 'Pothole', flood_forecast: 'Flood forecast', road_risk: 'Road risk', quality: 'Pollution', gate: 'Gate', pit: 'Recharge pit' }

export default function Alerts({ d }) {
  const [kind, setKind] = useState('ALL')
  const [sev, setSev] = useState('ALL')
  const svc = d.services.alerts
  const tg = svc?.detail || {}
  const list = d.alerts.filter((a) => (kind === 'ALL' || a.kind === kind) && (sev === 'ALL' || (a.severity || 'info') === sev))

  return (
    <div className="grid">
      <Card title="Telegram">
        {svc ? (
          <>
            <p>Bot {tg.bot || ''} {serviceAlive(svc) && svc.status !== 'error' ? <Badge colour="#16a34a">running</Badge> : <Badge colour="#dc2626">not running</Badge>}</p>
            <p className="muted small">Subscribers: {tg.subscribers ?? '—'} · sent this session: {tg.sent_this_session ?? 0} · last seen {ago(svc.last_seen)}</p>
            {tg.last_error && <p className="err small">{tg.last_error}</p>}
          </>
        ) : <Empty>alerts.py has not reported yet.</Empty>}
      </Card>
      <Card title="Counts">
        <table><tbody>{Object.entries(KINDS).map(([k, v]) => (
          <tr key={k}><td>{v}</td><td>{d.alerts.filter((a) => a.kind === k).length}</td></tr>
        ))}</tbody></table>
      </Card>
      <Card wide title="Alerts" sub={`${list.length} shown`}
        actions={<div className="row">
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Category">
            <option value="ALL">All categories</option>{Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select value={sev} onChange={(e) => setSev(e.target.value)} aria-label="Severity">
            <option value="ALL">All severities</option><option value="critical">critical</option><option value="warning">warning</option><option value="info">info</option>
          </select>
        </div>}>
        {list.length ? (
          <div className="tablewrap"><table>
            <thead><tr><th>Time</th><th>Category</th><th>Severity</th><th>Message</th><th>Where</th><th>Telegram</th></tr></thead>
            <tbody>{list.map((a) => (
              <tr key={a.id}>
                <td>{time(a.created_at)}</td><td>{KINDS[a.kind] || a.kind}</td>
                <td><Badge colour={SEV_COLOUR[a.severity] || '#38bdf8'}>{a.severity || 'info'}</Badge></td>
                <td className="pre">{a.message}</td>
                <td>{a.lat != null ? `${a.lat.toFixed(4)}, ${a.lng.toFixed(4)}` : (a.segment || a.node_id || '—')}</td>
                <td>{a.sent_telegram ? 'sent' : '—'}</td>
              </tr>
            ))}</tbody>
          </table></div>
        ) : <Empty>No alerts match.</Empty>}
      </Card>
    </div>
  )
}
