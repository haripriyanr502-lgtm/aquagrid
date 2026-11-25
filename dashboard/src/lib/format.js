export const REAL = 'SS-01'
export const CENTER = [12.95, 77.63]

export function ago(ts) {
  if (!ts) return 'never'
  const s = Math.round((Date.now() - new Date(ts).getTime()) / 1000)
  if (s < 0) return 'just now'
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

export const time = (ts) => (ts ? new Date(ts).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—')
export const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`)
export const num = (v, d = 1) => (v == null || Number.isNaN(+v) ? '—' : (+v).toFixed(d))

export function levelColour(r) {
  if (!r) return '#64748b'
  if (r.reason === 'dirty_water_to_drain') return '#a16207'
  if (r.level_pct >= 85) return '#dc2626'
  if (r.level_pct >= 60) return '#f97316'
  if (r.level_pct >= 35) return '#eab308'
  return '#22c55e'
}

export const RISK_COLOUR = { CRITICAL: '#dc2626', HIGH: '#f97316', MEDIUM: '#eab308', LOW: '#22c55e', UNKNOWN: '#64748b' }
export const SEV_COLOUR = { HIGH: '#dc2626', MEDIUM: '#f97316', LOW: '#eab308', critical: '#dc2626', warning: '#f97316', info: '#38bdf8' }

export const REASON_TEXT = {
  open: 'Recharging groundwater',
  below_threshold: 'Normal',
  first_flush_to_drain: 'First flush → drain',
  dirty_water_to_drain: 'Polluted → drain (aquifer protected)',
  pit_full: 'Recharge pit full',
  dry_run_protect: 'Low water',
  sensor_fault: 'SENSOR FAULT',
  forced_closed: 'Gate held closed',
}

export const LOCATION_TEXT = {
  gps_exif: 'Photo GPS (EXIF)',
  gps_device: 'GPS module',
  gps_browser: 'Phone/browser GPS',
  manual: 'Entered manually',
  none: 'Location unavailable',
  legacy_random: 'Not real (old random value)',
}

export const hasRealLocation = (p) =>
  p.lat != null && p.lng != null && p.location_source && !['none', 'legacy_random'].includes(p.location_source)

export const isOnline = (r, seconds = 30) => r && Date.now() - new Date(r.created_at).getTime() < seconds * 1000
export const serviceAlive = (s, seconds = 60) => s && Date.now() - new Date(s.last_seen).getTime() < seconds * 1000
export const isSimulated = (node, reading) => node?.kind !== 'real' || reading?.is_simulated === true

export const REPAIR_STATUSES = ['Reported', 'Under Review', 'Repair Scheduled', 'In Progress', 'Completed']
