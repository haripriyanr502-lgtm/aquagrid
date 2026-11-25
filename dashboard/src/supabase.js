import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const key = import.meta.env.VITE_SUPABASE_ANON_KEY

export const isConfigured = Boolean(url && key && !url.includes('YOUR-PROJECT'))
export const supabase = isConfigured ? createClient(url, key) : null

// send(target, ...commands) e.g. send('SS-01', 'R:ON')  - returns an error message or null
export async function send(target, ...commands) {
  if (!supabase) return 'Supabase is not configured'
  const rows = commands.map((command) => ({ node_id: target, command }))
  const { error } = await supabase.from('commands').insert(rows)
  return error ? error.message : null
}
