import { useState } from 'react'
import { supabase } from '../supabase'
import { Card, Empty, Badge, Notice, AuthBox } from '../components/ui'
import { REPAIR_STATUSES, ago, time } from '../lib/format'

const URG = { IMMEDIATE: '#dc2626', HIGH: '#f97316', MEDIUM: '#eab308', LOW: '#22c55e', MONITOR: '#64748b' }

function Ticket({ t, session, onError }) {
  const [status, setStatus] = useState(t.status || 'Reported')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true)
    const { error } = await supabase.from('repair_tickets').update({ status, status_note: note || null }).eq('segment', t.segment)
    setBusy(false)
    if (error) onError(`Could not update ${t.name}: ${error.message}`)
    else setNote('')
  }

  return (
    <div className="ticket">
      <div className="ticket-head">
        <span className="rank">#{t.priority_rank}</span>
        <b>{t.name}</b>
        <Badge colour={URG[t.urgency]}>{t.urgency}</Badge>
        <span className="score">{t.priority_score}/100</span>
      </div>
      <ul className="reasons">{(t.reasons || []).map((r, i) => <li key={i}>{r}</li>)}</ul>
      <p className="muted small">
        Factors — risk {t.factors?.risk ?? '—'} · high-severity share {t.factors?.high_severity_share ?? '—'} ·
        repeat days {t.factors?.repeat_days ?? '—'} · confirmed share {t.factors?.confirmed_share ?? '—'} · recalculated {ago(t.computed_at)}
      </p>
      <div className="row">
        <label>Status{' '}
          <select value={status} disabled={!session} onChange={(e) => setStatus(e.target.value)}>
            {REPAIR_STATUSES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
        <input placeholder="note (e.g. BBMP ticket no.)" value={note} disabled={!session} onChange={(e) => setNote(e.target.value)} aria-label="Status note" />
        <button disabled={!session || busy || (status === t.status && !note)} onClick={save}>{busy ? 'Saving…' : 'Update'}</button>
      </div>
      <p className="muted small">Current: <b>{t.status}</b>{t.status_updated_at && ` · changed ${time(t.status_updated_at)} by ${t.updated_by}`}</p>
    </div>
  )
}

export default function Repairs({ d }) {
  const [err, setErr] = useState(null)
  return (
    <div className="grid">
      <Card wide title="Repair priority" sub="priority = 55% road risk + 20% high-severity share + 15% repeat detections + 10% team-confirmed">
        <AuthBox session={d.session} />
        {err && <Notice kind="error">{err}</Notice>}
        <Notice kind="info">Status changes are made by signed-in team members only and are logged. “Completed” means a person confirmed it — AquaGrid never marks a repair done by itself.</Notice>
        {d.repairs.length ? d.repairs.map((t) => <Ticket key={t.segment + t.status} t={t} session={d.session} onError={setErr} />)
          : <Empty>No priorities yet — run <code>python repair_priority.py</code> (after road_risk.py).</Empty>}
      </Card>
      <Card wide title="Status history">
        {d.repairLog.length ? (
          <table>
            <thead><tr><th>When</th><th>Road</th><th>From</th><th>To</th><th>Note</th><th>By</th></tr></thead>
            <tbody>{d.repairLog.map((l) => (
              <tr key={l.id}><td>{time(l.created_at)}</td><td>{l.segment}</td><td>{l.old_status}</td><td>{l.new_status}</td><td>{l.note || '—'}</td><td>{l.changed_by}</td></tr>
            ))}</tbody>
          </table>
        ) : <Empty>No status changes yet.</Empty>}
      </Card>
    </div>
  )
}
