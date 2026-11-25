import { useCallback, useEffect, useState } from 'react'
import { supabase } from '../supabase'
import { REAL } from './format'

// one place that loads everything and keeps it live
const EMPTY = {
  nodes: [], latest: {}, history: [], runs: [], alerts: [], potholes: [], roads: [], riskHistory: [],
  repairs: [], repairLog: [], jobs: [], services: {}, commands: [],
}

async function q(promise, label, problems) {
  const { data, error } = await promise
  if (error) {
    problems.push(`${label}: ${error.message}`)
    return null
  }
  return data
}

export function useAquaGrid() {
  const [data, setData] = useState(EMPTY)
  const [loading, setLoading] = useState(true)
  const [problems, setProblems] = useState([])
  const [dbOk, setDbOk] = useState(null)
  const [realtime, setRealtime] = useState('connecting')
  const [session, setSession] = useState(null)

  const load = useCallback(async () => {
    if (!supabase) { setLoading(false); return }
    const p = []
    const [nodes, readings, history, runs, alerts, potholes, roads, riskHistory, repairs, repairLog, jobs, services, commands] =
      await Promise.all([
        q(supabase.from('nodes').select('*'), 'nodes', p),
        q(supabase.from('readings').select('*').order('id', { ascending: false }).limit(800), 'readings', p),
        q(supabase.from('readings').select('*').eq('node_id', REAL).order('id', { ascending: false }).limit(180), 'readings', p),
        q(supabase.from('runs').select('*').order('id', { ascending: false }).limit(10), 'runs', p),
        q(supabase.from('alerts').select('*').order('id', { ascending: false }).limit(100), 'alerts', p),
        q(supabase.from('potholes').select('*').order('id', { ascending: false }).limit(500), 'potholes', p),
        q(supabase.from('road_risk').select('*'), 'road_risk', p),
        q(supabase.from('road_risk_history').select('*').order('id', { ascending: false }).limit(600), 'road_risk_history (run migration 002)', p),
        q(supabase.from('repair_tickets').select('*').order('priority_rank'), 'repair_tickets (run migration 002)', p),
        q(supabase.from('repair_status_log').select('*').order('id', { ascending: false }).limit(50), 'repair_status_log', p),
        q(supabase.from('detection_jobs').select('*').order('id', { ascending: false }).limit(20), 'detection_jobs', p),
        q(supabase.from('service_status').select('*'), 'service_status', p),
        q(supabase.from('commands').select('*').order('id', { ascending: false }).limit(40), 'commands', p),
      ])
    const latest = {}
    ;(readings || []).forEach((r) => { if (!latest[r.node_id]) latest[r.node_id] = r })
    const svc = {}
    ;(services || []).forEach((s) => { svc[s.service] = s })
    setData({
      nodes: nodes || [], latest, history: (history || []).reverse(), runs: runs || [], alerts: alerts || [],
      potholes: potholes || [], roads: roads || [], riskHistory: (riskHistory || []).reverse(),
      repairs: repairs || [], repairLog: repairLog || [], jobs: jobs || [], services: svc, commands: commands || [],
    })
    setDbOk(nodes !== null)
    setProblems(p)
    setLoading(false)
  }, [])

  useEffect(() => {
    if (!supabase) { setLoading(false); return }
    load()
    supabase.auth.getSession().then(({ data: s }) => setSession(s.session))
    const { data: authSub } = supabase.auth.onAuthStateChange((_e, s) => setSession(s))

    const upsertBy = (key) => (list, row) => [row, ...list.filter((x) => x[key] !== row[key])]
    const on = (table, fn, event = '*') => ({ table, fn, event })
    const handlers = [
      on('readings', (x) => setData((d) => ({
        ...d, latest: { ...d.latest, [x.node_id]: x },
        history: x.node_id === REAL ? [...d.history.slice(-179), x] : d.history,
      })), 'INSERT'),
      on('runs', (x) => setData((d) => ({ ...d, runs: [x, ...d.runs].slice(0, 10) })), 'INSERT'),
      on('alerts', (x) => setData((d) => ({ ...d, alerts: upsertBy('id')(d.alerts, x).slice(0, 100) }))),
      on('potholes', (x) => setData((d) => ({ ...d, potholes: upsertBy('id')(d.potholes, x) }))),
      on('road_risk', (x) => setData((d) => ({ ...d, roads: upsertBy('segment')(d.roads, x) }))),
      on('road_risk_history', (x) => setData((d) => ({ ...d, riskHistory: [...d.riskHistory.slice(-599), x] })), 'INSERT'),
      on('repair_tickets', (x) => setData((d) => ({
        ...d, repairs: upsertBy('segment')(d.repairs, x).sort((a, b) => (a.priority_rank ?? 99) - (b.priority_rank ?? 99)),
      }))),
      on('detection_jobs', (x) => setData((d) => ({ ...d, jobs: upsertBy('id')(d.jobs, x).sort((a, b) => b.id - a.id) }))),
      on('service_status', (x) => setData((d) => ({ ...d, services: { ...d.services, [x.service]: x } }))),
      on('commands', (x) => setData((d) => ({ ...d, commands: upsertBy('id')(d.commands, x).sort((a, b) => b.id - a.id).slice(0, 40) }))),
    ]
    let ch = supabase.channel('aquagrid-live')
    handlers.forEach(({ table, fn, event }) => {
      ch = ch.on('postgres_changes', { event, schema: 'public', table }, ({ new: row }) => row && fn(row))
    })
    ch.subscribe((status) => setRealtime(status === 'SUBSCRIBED' ? 'live' : status.toLowerCase()))

    // repair log has no realtime subscription: refresh it every 20 s
    const t = setInterval(async () => {
      const { data: log } = await supabase.from('repair_status_log').select('*').order('id', { ascending: false }).limit(50)
      if (log) setData((d) => ({ ...d, repairLog: log }))
    }, 20000)
    return () => { supabase.removeChannel(ch); authSub?.subscription?.unsubscribe(); clearInterval(t) }
  }, [load])

  return { ...data, loading, problems, dbOk, realtime, session, reload: load }
}
