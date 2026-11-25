import { useState } from 'react'
import { send } from '../supabase'
import { Card, Empty, Badge, Notice } from '../components/ui'
import { REAL, ago } from '../lib/format'

export default function Control({ d }) {
  const [threshold, setThreshold] = useState(60)
  const [err, setErr] = useState(null)
  const real = d.latest[REAL]
  const run = async (target, ...cmds) => setErr(await send(target, ...cmds))

  return (
    <div className="grid">
      <Card title="Simulation">
        <div className="btns">
          <button className="primary" onClick={async () => { await run(REAL, 'D:AUTO', 'R:ON'); await run('SIM', 'STORM'); await run('BRAIN', 'STORM') }}>🌧️ Start Monsoon</button>
          <button onClick={async () => { await run(REAL, 'R:OFF'); await run('SIM', 'STOP') }}>Stop simulation</button>
          <button onClick={() => run('SIM', 'RESET')}>Reset simulated city</button>
          <button onClick={() => run('BRAIN', 'STORM')}>Run twin forecast</button>
        </div>
        <p className="muted small">Start Monsoon: rain pump on the real model (R:ON), a 3-minute storm across the simulated nodes, and a digital-twin run (1 s = 1 simulated minute).</p>
        {err && <Notice kind="error">{err}</Notice>}
      </Card>

      <Card title="Silk Board node — gate" sub={real?.is_simulated ? 'bridge --simulate' : ''}>
        <label>Gate threshold: <b>{threshold}%</b></label>
        <input type="range" min="10" max="90" value={threshold} aria-label="Gate threshold"
          onChange={(e) => setThreshold(+e.target.value)}
          onMouseUp={() => run(REAL, `T:${threshold}`)} onTouchEnd={() => run(REAL, `T:${threshold}`)} onKeyUp={() => run(REAL, `T:${threshold}`)} />
        <div className="btns">
          <button onClick={() => run(REAL, 'D:AUTO')}>Auto</button>
          <button onClick={() => run(REAL, 'D:ON')}>Request open</button>
          <button onClick={() => run(REAL, 'D:OFF')}>Force close</button>
          <button onClick={() => run(REAL, 'RST:L')}>Reset litres</button>
        </div>
        <p className="muted small">The node's safeties (dry-run, first flush, dirty water, pit full) always win over “Request open”.</p>
        {real ? <p>Now: level {real.level_pct}% · gate {real.gate_open ? 'OPEN' : 'shut'} · mode {real.mode} · threshold {real.threshold}%</p>
          : <Empty>No reading from SS-01 yet.</Empty>}
      </Card>

      <Card wide title="Command status" sub="pending = waiting for bridge.py / simulator.py / brain.py to pick it up">
        {d.commands.length ? (
          <table>
            <thead><tr><th>#</th><th>Target</th><th>Command</th><th>Status</th><th>Result</th><th>Sent</th></tr></thead>
            <tbody>{d.commands.map((c) => (
              <tr key={c.id}><td>{c.id}</td><td>{c.node_id}</td><td><code>{c.command}</code></td>
                <td><Badge colour={{ done: '#16a34a', pending: '#eab308', rejected: '#dc2626', failed: '#dc2626' }[c.status] || '#64748b'}>{c.status}</Badge></td>
                <td className="small">{c.result || '—'}</td><td>{ago(c.created_at)}</td></tr>
            ))}</tbody>
          </table>
        ) : <Empty>No commands yet (needs the “public read commands” policy from migration 002).</Empty>}
      </Card>
    </div>
  )
}
