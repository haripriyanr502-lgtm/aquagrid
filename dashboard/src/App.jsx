import { useEffect, useRef, useState } from 'react'
import { isConfigured } from './supabase'
import { useAquaGrid } from './lib/useAquaGrid'
import { Loading, Notice } from './components/ui'
import Overview from './pages/Overview'
import LiveMap from './pages/LiveMap'
import Flood from './pages/Flood'
import Twin from './pages/Twin'
import DrainX from './pages/DrainX'
import RoadRisk from './pages/RoadRisk'
import Repairs from './pages/Repairs'
import Alerts from './pages/Alerts'
import Control from './pages/Control'
import Health from './pages/Health'

export const PAGES = [
  ['overview', 'Overview', Overview],
  ['map', 'Live Map', LiveMap],
  ['flood', 'Flood Monitoring', Flood],
  ['twin', 'Digital Twin', Twin],
  ['drainx', 'DrainX · Potholes', DrainX],
  ['risk', 'Road Risk', RoadRisk],
  ['repairs', 'Repairs', Repairs],
  ['alerts', 'Alerts', Alerts],
  ['control', 'Control Room', Control],
  ['health', 'System Health', Health],
]

const fromHash = () => {
  const h = window.location.hash.replace('#', '')
  return PAGES.some(([k]) => k === h) ? h : 'overview'
}

export default function App() {
  const d = useAquaGrid()
  const [page, setPage] = useState(fromHash)
  const [toast, setToast] = useState(null)
  const lastAlert = useRef(null)

  useEffect(() => {
    const f = () => setPage(fromHash())
    window.addEventListener('hashchange', f)
    return () => window.removeEventListener('hashchange', f)
  }, [])

  // pop up every NEW alert that arrives while the page is open
  useEffect(() => {
    const newest = d.alerts[0]
    if (!newest) return
    if (lastAlert.current !== null && newest.id > lastAlert.current) {
      setToast(newest)
      try { navigator.vibrate?.([200, 100, 200]) } catch { /* not supported */ }
      const t = setTimeout(() => setToast(null), 8000)
      lastAlert.current = newest.id
      return () => clearTimeout(t)
    }
    lastAlert.current = Math.max(lastAlert.current ?? 0, newest.id)
  }, [d.alerts])

  const go = (k) => { window.location.hash = k; setPage(k) }
  const Page = PAGES.find(([k]) => k === page)[2]

  if (!isConfigured) {
    return (
      <div className="app">
        <h1>AquaGrid</h1>
        <Notice kind="error">
          Supabase is not configured. Copy <code>dashboard/.env.example</code> to <code>dashboard/.env</code>, paste the
          Project URL and the <b>anon</b> key, then restart <code>npm run dev</code>.
        </Notice>
      </div>
    )
  }

  return (
    <div className="app">
      {toast && (
        <div className={'toast ' + (toast.severity || 'info')} role="alert" onClick={() => setToast(null)}>
          ⚠️ {toast.message}
        </div>
      )}
      <header>
        <div>
          <h1>AquaGrid <span className="sub">with DrainX road intelligence</span></h1>
          <p className="sub">Stormwater, flood forecasting, groundwater recharge and pothole monitoring · Bengaluru</p>
        </div>
        <span className={d.realtime === 'live' ? 'pill on' : 'pill'}>{d.realtime === 'live' ? '● LIVE' : `○ ${d.realtime}`}</span>
      </header>
      <nav aria-label="Sections">
        {PAGES.map(([k, label]) => (
          <button key={k} className={k === page ? 'active' : ''} aria-current={k === page ? 'page' : undefined} onClick={() => go(k)}>{label}</button>
        ))}
      </nav>
      {d.problems.length > 0 && page !== 'health' && (
        <Notice kind="warn">Some data could not be loaded ({d.problems.length}). See System Health. Has database/002_aquagrid_upgrade.sql been run?</Notice>
      )}
      <main>{d.loading ? <Loading /> : <Page d={d} go={go} />}</main>
      <footer className="muted small">Simulated nodes and the illustrative flood model are labelled as such. Coordinates of nodes and road segments are approximate.</footer>
    </div>
  )
}
