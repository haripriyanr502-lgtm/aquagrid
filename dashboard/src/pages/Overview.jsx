import { Card, Kpi, Badge, Empty } from '../components/ui'
import { ago, hasRealLocation, isOnline, serviceAlive, RISK_COLOUR, SEV_COLOUR } from '../lib/format'

export default function Overview({ d, go }) {
  const readings = Object.values(d.latest)
  const online = readings.filter((r) => isOnline(r)).length
  const floodRisk = readings.filter((r) => r.level_pct >= 60).length
  const critical = d.roads.filter((r) => r.label === 'CRITICAL').length
  const high = d.roads.filter((r) => r.label === 'HIGH').length
  const located = d.potholes.filter(hasRealLocation).length
  const services = Object.values(d.services)
  const alive = services.filter((s) => serviceAlive(s) && s.status !== 'error').length
  const litres = readings.reduce((s, r) => s + (r.litres_total || 0), 0)
  const realLitres = readings.filter((r) => r.node_id === 'SS-01' && !r.is_simulated).reduce((s, r) => s + (r.litres_total || 0), 0)
  const run = d.runs[0]

  return (
    <>
      <section className="kpis">
        <Kpi label="Monitoring nodes" value={d.nodes.length} hint="1 real + simulated virtual nodes" />
        <Kpi label="Nodes online (30 s)" value={`${online}/${d.nodes.length}`} />
        <Kpi label="Potholes detected" value={d.potholes.length} hint={`${located} with a real location`} />
        <Kpi label="Flood-risk locations now" value={floodRisk} tone={floodRisk ? 'warn' : ''} />
        <Kpi label="Critical / high roads" value={`${critical} / ${high}`} tone={critical ? 'bad' : ''} />
        <Kpi label="Services healthy" value={`${alive}/${services.length || 0}`} tone={alive === services.length && alive ? 'good' : 'warn'} />
      </section>

      <div className="grid">
        <Card title="Latest digital-twin forecast" sub="illustrative model">
          {run ? (
            <>
              <p className="headline">
                Modelled road flooding: <b>{run.flood_m3_baseline} m³</b> today → <b>{run.flood_m3_optimised} m³</b> with
                AquaGrid control (<b>-{run.reduction_pct}%</b>)
              </p>
              <p className="muted">{run.scenario} · {run.rain_total_mm} mm rain · {ago(run.created_at)}</p>
              <button onClick={() => go('twin')}>Open digital twin →</button>
            </>
          ) : <Empty>No forecast yet — start brain.py and press “Run twin forecast” in the Control Room.</Empty>}
        </Card>

        <Card title="Water recharged">
          <p className="big">{Math.round(litres).toLocaleString('en-IN')} L</p>
          <p className="muted">Real node (hardware): {realLitres.toFixed(1)} L · the rest comes from simulated virtual nodes.</p>
        </Card>

        <Card title="Road risk ranking" actions={<button onClick={() => go('risk')}>Details →</button>}>
          {d.roads.length ? (
            <table><tbody>
              {[...d.roads].sort((a, b) => b.risk - a.risk).map((r) => (
                <tr key={r.segment}><td>{r.name}</td><td>{(r.risk ?? 0).toFixed(2)}</td>
                  <td><Badge colour={RISK_COLOUR[r.label]}>{r.label}</Badge>{r.flood_available === false && <span className="muted small"> no flood data</span>}</td></tr>
              ))}
            </tbody></table>
          ) : <Empty>Start road_risk.py to calculate risk.</Empty>}
        </Card>

        <Card title="Recent alerts" actions={<button onClick={() => go('alerts')}>All alerts →</button>}>
          {d.alerts.length ? (
            <ul className="alerts">
              {d.alerts.slice(0, 6).map((a) => (
                <li key={a.id}><Badge colour={SEV_COLOUR[a.severity] || '#38bdf8'}>{a.severity || 'info'}</Badge>{' '}
                  <span className="muted">{ago(a.created_at)}</span> {a.message}</li>
              ))}
            </ul>
          ) : <Empty>No alerts yet.</Empty>}
        </Card>
      </div>
    </>
  )
}
