import { useState } from 'react'
import { supabase } from '../supabase'

export function Card({ title, sub, children, wide, actions }) {
  return (
    <section className={'card' + (wide ? ' wide' : '')}>
      {(title || actions) && (
        <div className="card-head">
          <h2>{title} {sub && <small>{sub}</small>}</h2>
          {actions}
        </div>
      )}
      {children}
    </section>
  )
}

export function Kpi({ label, value, tone, hint }) {
  return (
    <div className={'kpi ' + (tone || '')} title={hint}>
      <div className="v">{value}</div>
      <div className="l">{label}</div>
    </div>
  )
}

export function Badge({ children, colour, outline }) {
  return (
    <span className={'badge' + (outline ? ' outline' : '')} style={{ background: outline ? 'transparent' : colour, borderColor: colour, color: outline ? colour : '#fff' }}>
      {children}
    </span>
  )
}

export const SimTag = () => <span className="sim">SIMULATED</span>
export const RealTag = () => <span className="realtag">REAL</span>

export function Empty({ children }) {
  return <p className="empty">{children}</p>
}

export function Notice({ kind = 'info', children }) {
  return <div className={'notice ' + kind} role={kind === 'error' ? 'alert' : 'note'}>{children}</div>
}

export function Loading() {
  return <div className="loading" aria-live="polite">Loading live data…</div>
}

export function Bar({ value, colour, max = 1 }) {
  const w = Math.max(0, Math.min(100, ((value || 0) / max) * 100))
  return <div className="bar"><div style={{ width: `${w}%`, background: colour }} /></div>
}

export function AuthBox({ session }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  if (!supabase) return null
  if (session) {
    return (
      <div className="auth signed">
        Signed in as <b>{session.user.email}</b>
        <button onClick={() => supabase.auth.signOut()}>Sign out</button>
      </div>
    )
  }
  async function signIn(e) {
    e.preventDefault()
    setBusy(true)
    setMsg(null)
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    setBusy(false)
    if (error) setMsg(error.message)
  }
  return (
    <form className="auth" onSubmit={signIn}>
      <span>Team sign-in required to change data</span>
      <input type="email" required placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Email" />
      <input type="password" required placeholder="password" value={password} onChange={(e) => setPassword(e.target.value)} aria-label="Password" />
      <button disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      {msg && <span className="err">{msg}</span>}
    </form>
  )
}
