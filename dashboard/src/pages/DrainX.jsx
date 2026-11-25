import { useState } from 'react'
import { supabase } from '../supabase'
import { Card, Empty, Notice, Badge, AuthBox } from '../components/ui'
import { LOCATION_TEXT, SEV_COLOUR, ago, hasRealLocation, serviceAlive, time } from '../lib/format'

const SEGMENTS = { J1: 'HSR Layout 27th Main', J2: 'Silk Board Junction', J3: 'BTM Layout 2nd Stage', J4: 'Madiwala' }

function ModelStatus({ svc }) {
  const det = svc?.detail || {}
  const m = det.metrics
  const alive = serviceAlive(svc, 90)
  return (
    <Card title="AI model" sub={det.model_version || ''}>
      {!svc && <Empty>No DrainX service has reported yet. Run <code>python pothole_detect.py --worker</code>.</Empty>}
      {svc && (
        <>
          <p>Model: {det.model_loaded ? <Badge colour="#16a34a">loaded</Badge> : <Badge colour="#dc2626">missing</Badge>}{' '}
            Worker: {alive && det.mode === 'worker' ? <Badge colour="#16a34a">online</Badge> : <Badge colour="#64748b">offline</Badge>}{' '}
            <span className="muted small">last seen {ago(svc.last_seen)}</span></p>
          {det.problem && <Notice kind="error">{det.problem}</Notice>}
          <p className="muted small">Classes: {(det.classes || []).join(', ') || '—'} · confidence threshold {det.min_conf ?? '—'} ·
            GPS module {det.gps_hardware ? 'connected' : 'not connected'}</p>
          {m ? (
            <table><tbody>
              <tr><td>Precision</td><td>{m.precision}</td><td>Recall</td><td>{m.recall}</td></tr>
              <tr><td>mAP50</td><td>{m.map50}</td><td>mAP50-95</td><td>{m.map50_95}</td></tr>
              <tr><td>True positives</td><td>{m.true_positives ?? '—'}</td><td>False pos. / neg.</td><td>{m.false_positives ?? '—'} / {m.false_negatives ?? '—'}</td></tr>
              <tr><td colSpan={4} className="muted small">Evaluated on the {m.split} split · {time(m.evaluated_at)}</td></tr>
            </tbody></table>
          ) : <Notice kind="warn">Not evaluated yet — no accuracy figures are shown until <code>python evaluate_model.py --data …/data.yaml</code> has been run.</Notice>}
        </>
      )}
    </Card>
  )
}

function Upload({ session, jobs }) {
  const [file, setFile] = useState(null)
  const [segment, setSegment] = useState('J2')
  const [locMode, setLocMode] = useState('none')
  const [manual, setManual] = useState({ lat: '', lng: '' })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)

  function getGps() {
    return new Promise((resolve) => {
      if (!navigator.geolocation) return resolve(null)
      navigator.geolocation.getCurrentPosition(
        (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy }),
        () => resolve(null), { enableHighAccuracy: true, timeout: 10000 })
    })
  }

  async function submit(e) {
    e.preventDefault()
    if (!file) return setMsg({ kind: 'error', text: 'Choose an image or video first.' })
    if (file.size > 50 * 1024 * 1024) return setMsg({ kind: 'error', text: 'File is larger than 50 MB.' })
    setBusy(true); setMsg(null)
    let lat = null, lng = null, source = 'none'
    if (locMode === 'gps') {
      const g = await getGps()
      if (!g) { setBusy(false); return setMsg({ kind: 'error', text: 'Could not read this device’s GPS. Allow location access or choose another option.' }) }
      lat = g.lat; lng = g.lng; source = 'gps_browser'
    } else if (locMode === 'manual') {
      lat = parseFloat(manual.lat); lng = parseFloat(manual.lng)
      if (Number.isNaN(lat) || Number.isNaN(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) {
        setBusy(false); return setMsg({ kind: 'error', text: 'Enter a valid latitude and longitude.' })
      }
      source = 'manual'
    }
    const isVideo = file.type.startsWith('video/')
    const safe = file.name.replace(/[^a-zA-Z0-9._-]/g, '_')
    const path = `uploads/${Date.now()}_${safe}`
    const up = await supabase.storage.from('detections').upload(path, file, { contentType: file.type })
    if (up.error) { setBusy(false); return setMsg({ kind: 'error', text: `Upload failed: ${up.error.message}` }) }
    const { error } = await supabase.from('detection_jobs').insert({
      file_path: path, file_type: isVideo ? 'video' : 'image', segment, lat, lng, location_source: source,
      created_by: session.user.email,
    })
    setBusy(false)
    if (error) return setMsg({ kind: 'error', text: `Could not queue detection: ${error.message}` })
    setMsg({ kind: 'ok', text: 'Uploaded. The DrainX worker will analyse it in a few seconds.' })
    setFile(null)
  }

  return (
    <Card title="Run detection" sub="image, video or camera">
      <AuthBox session={session} />
      <form onSubmit={submit} className="form">
        <label>Photo or video
          <input type="file" accept="image/*,video/*" disabled={!session} onChange={(e) => setFile(e.target.files?.[0] || null)} />
        </label>
        <label>…or take a photo now (phone camera)
          <input type="file" accept="image/*" capture="environment" disabled={!session} onChange={(e) => setFile(e.target.files?.[0] || null)} />
        </label>
        <label>Road segment
          <select value={segment} onChange={(e) => setSegment(e.target.value)}>
            {Object.entries(SEGMENTS).map(([k, v]) => <option key={k} value={k}>{v} ({k})</option>)}
          </select>
        </label>
        <fieldset>
          <legend>Location</legend>
          <label><input type="radio" name="loc" checked={locMode === 'none'} onChange={() => setLocMode('none')} /> Use photo GPS if present, otherwise “unavailable”</label>
          <label><input type="radio" name="loc" checked={locMode === 'gps'} onChange={() => setLocMode('gps')} /> This device’s GPS (only if you are at the pothole)</label>
          <label><input type="radio" name="loc" checked={locMode === 'manual'} onChange={() => setLocMode('manual')} /> Enter coordinates</label>
          {locMode === 'manual' && (
            <div className="row">
              <input placeholder="latitude" value={manual.lat} onChange={(e) => setManual({ ...manual, lat: e.target.value })} aria-label="Latitude" />
              <input placeholder="longitude" value={manual.lng} onChange={(e) => setManual({ ...manual, lng: e.target.value })} aria-label="Longitude" />
            </div>
          )}
        </fieldset>
        <button className="primary" disabled={!session || busy || !file}>{busy ? 'Uploading…' : 'Detect potholes'}</button>
        {msg && <Notice kind={msg.kind === 'ok' ? 'info' : 'error'}>{msg.text}</Notice>}
      </form>
      <h3>Recent jobs</h3>
      {jobs.length ? (
        <ul className="jobs">{jobs.slice(0, 6).map((j) => (
          <li key={j.id}>
            <b>#{j.id}</b> {j.file_type} · {SEGMENTS[j.segment] || j.segment} · <Badge colour={{ done: '#16a34a', failed: '#dc2626', processing: '#0ea5e9' }[j.status] || '#64748b'}>{j.status}</Badge>
            {j.status === 'done' && j.result && <> · {j.result.potholes} pothole(s){j.result.max_confidence != null && ` · max ${Math.round(j.result.max_confidence * 100)}%`}{j.result.severity && ` · ${j.result.severity}`}</>}
            {j.status === 'failed' && <span className="err"> {j.error}</span>}
            {j.result?.image_url && <div><img src={j.result.image_url} alt={`Detection result for job ${j.id}`} className="thumb" /></div>}
          </li>
        ))}</ul>
      ) : <Empty>No uploads yet.</Empty>}
    </Card>
  )
}

export default function DrainX({ d }) {
  const [seg, setSeg] = useState('ALL')
  const [msg, setMsg] = useState(null)
  const list = d.potholes.filter((p) => seg === 'ALL' || p.road_segment === seg)

  async function verify(p, verification) {
    const { error } = await supabase.from('potholes').update({ verification }).eq('id', p.id)
    setMsg(error ? `Update failed: ${error.message}` : null)
  }

  return (
    <div className="grid">
      <ModelStatus svc={d.services.drainx} />
      <Upload session={d.session} jobs={d.jobs} />
      <Card wide title="Pothole history" sub={`${list.length} records`}
        actions={<select value={seg} onChange={(e) => setSeg(e.target.value)} aria-label="Filter by road">
          <option value="ALL">All roads</option>{Object.entries(SEGMENTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>}>
        {msg && <Notice kind="error">{msg}</Notice>}
        {list.length ? (
          <div className="tablewrap"><table>
            <thead><tr><th>Time</th><th>Road</th><th>Confidence</th><th>Severity</th><th>Location</th><th>Source</th><th>Image</th><th>Verification</th></tr></thead>
            <tbody>{list.map((p) => (
              <tr key={p.id}>
                <td>{time(p.created_at)}</td><td>{SEGMENTS[p.road_segment] || p.road_segment}</td>
                <td>{Math.round((p.confidence || 0) * 100)}%</td>
                <td>{p.severity ? <Badge colour={SEV_COLOUR[p.severity]}>{p.severity}</Badge> : '—'}</td>
                <td>{hasRealLocation(p) ? `${p.lat.toFixed(5)}, ${p.lng.toFixed(5)}` : <span className="muted">{LOCATION_TEXT[p.location_source] || 'Location unavailable'}</span>}
                  {hasRealLocation(p) && <div className="muted small">{LOCATION_TEXT[p.location_source]}</div>}</td>
                <td>{p.source_type || '—'}<div className="muted small">{p.source_ref}</div></td>
                <td>{p.image_url ? <a href={p.image_url} target="_blank" rel="noreferrer">open</a> : '—'}</td>
                <td>{p.verification || 'unverified'}
                  {d.session && (
                    <div className="mini">
                      <button onClick={() => verify(p, 'confirmed')}>Confirm</button>
                      <button onClick={() => verify(p, 'false_positive')}>False +</button>
                    </div>
                  )}</td>
              </tr>
            ))}</tbody>
          </table></div>
        ) : <Empty>No detections yet.</Empty>}
        <p className="muted small">Severity is a heuristic from how much of the frame the pothole covers (≥15 % high, ≥5 % medium). False positives are excluded from road risk.</p>
      </Card>
    </div>
  )
}
