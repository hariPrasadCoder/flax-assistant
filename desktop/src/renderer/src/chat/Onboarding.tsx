import { motion, AnimatePresence } from 'framer-motion'
import { useState, useEffect } from 'react'
import { createClient, SupabaseClient } from '@supabase/supabase-js'

const PERSONAL_DOMAINS = new Set([
  'gmail.com', 'googlemail.com',
  'outlook.com', 'hotmail.com', 'hotmail.co.uk', 'hotmail.fr', 'live.com', 'msn.com',
  'yahoo.com', 'yahoo.co.uk', 'yahoo.fr', 'yahoo.de', 'yahoo.in', 'ymail.com',
  'icloud.com', 'me.com', 'mac.com',
  'aol.com', 'protonmail.com', 'proton.me',
  'zoho.com', 'mail.com', 'inbox.com', 'gmx.com', 'gmx.net',
])

function isPersonalEmail(email: string): boolean {
  const domain = email.trim().toLowerCase().split('@')[1] ?? ''
  return PERSONAL_DOMAINS.has(domain)
}

interface Props {
  backendUrl: string
  onComplete: (userId: string, userName: string, teamId: string | null) => void
}

type Step = 'welcome' | 'email' | 'otp' | 'name' | 'team' | 'done'

// Inline Flaxie icon
function FlaxieBig() {
  return (
    <svg width="72" height="72" viewBox="0 0 100 100" fill="none">
      <defs>
        <linearGradient id="og" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#4A42D8" />
          <stop offset="100%" stopColor="#6B63E8" />
        </linearGradient>
      </defs>
      <circle cx="50" cy="50" r="46" fill="url(#og)" />
      <g fill="none" stroke="white" strokeWidth="2.5">
        {[0, 72, 144, 216, 288].map((r, i) => (
          <ellipse key={i} cx="50" cy="28" rx="10" ry="16" transform={`rotate(${r}, 50, 50)`} />
        ))}
      </g>
      <g stroke="white" strokeWidth="1.5" opacity="0.5">
        {[[50, 28], [69, 37], [62, 64], [38, 64], [31, 37]].map(([x2, y2], i) => (
          <line key={i} x1="50" y1="50" x2={x2} y2={y2} />
        ))}
      </g>
      <circle cx="50" cy="50" r="8" fill="white" />
      <circle cx="50" cy="50" r="4" fill="url(#og)" />
    </svg>
  )
}

export default function Onboarding({ backendUrl, onComplete }: Props) {
  const [step, setStep] = useState<Step>('welcome')
  const [supabase, setSupabase] = useState<SupabaseClient | null>(null)

  // Auth state
  const [email, setEmail] = useState('')
  const [otp, setOtp] = useState('')
  const [userId, setUserId] = useState('')
  const [userEmail, setUserEmail] = useState('')

  // Profile state
  const [name, setName] = useState('')

  // Team state
  const [teamChoice, setTeamChoice] = useState<'solo' | 'create' | 'join' | null>(null)
  const [teamName, setTeamName] = useState('')
  const [inviteCode, setInviteCode] = useState('')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [resendCooldown, setResendCooldown] = useState(0)

  // Load Supabase client — try env vars first (Vite injects VITE_ prefix), fall back to IPC
  useEffect(() => {
    const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
    const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined
    if (url && anonKey) {
      setSupabase(createClient(url, anonKey))
    } else {
      window.flaxie.getSupabaseConfig().then(({ url: u, anonKey: k }) => {
        if (u && k) setSupabase(createClient(u, k))
      })
    }
  }, [])

  // Resend cooldown timer
  useEffect(() => {
    if (resendCooldown <= 0) return
    const t = setTimeout(() => setResendCooldown((c) => c - 1), 1000)
    return () => clearTimeout(t)
  }, [resendCooldown])

  // ── Step handlers ──────────────────────────────────────────────────────────

  async function handleSendOtp() {
    if (!email.trim() || !supabase) return
    if (isPersonalEmail(email)) {
      setError('Please use your work email — personal addresses like Gmail or Outlook aren\'t allowed.')
      return
    }
    setLoading(true)
    setError('')
    try {
      const { error: err } = await supabase.auth.signInWithOtp({
        email: email.trim().toLowerCase(),
        options: { shouldCreateUser: true },
      })
      if (err) { setError(err.message); return }
      setStep('otp')
      setResendCooldown(60)
    } catch {
      setError('Could not send code — check your connection')
    } finally {
      setLoading(false)
    }
  }

  async function handleVerifyOtp() {
    if (otp.length < 8 || !supabase) return
    setLoading(true)
    setError('')
    try {
      const { data, error: err } = await supabase.auth.verifyOtp({
        email: email.trim().toLowerCase(),
        token: otp.trim(),
        type: 'email',
      })
      if (err || !data.user) { setError(err?.message || 'Invalid code'); return }

      const uid = data.user.id
      const uemail = data.user.email || email.trim().toLowerCase()
      setUserId(uid)
      setUserEmail(uemail)

      // Tell main process the real user ID so WebSocket reconnects correctly
      window.flaxie.setUserId(uid)
      localStorage.setItem('flaxie_user_id', uid)
      localStorage.setItem('flaxie_user_email', uemail)

      // Check if user already has a profile
      const meRes = await fetch(`${backendUrl}/api/auth/me?user_id=${uid}`)
      const me = await meRes.json()

      if (me && me.name) {
        // Returning user — restore their info and go straight to team step
        localStorage.setItem('flaxie_user_name', me.name)
        if (me.team_id) localStorage.setItem('flaxie_team_id', me.team_id)
        onComplete(uid, me.name, me.team_id || null)
      } else {
        // New user — needs to set their name
        setStep('name')
      }
    } catch {
      setError('Verification failed — try again')
    } finally {
      setLoading(false)
    }
  }

  async function handleSetupProfile() {
    if (!name.trim()) return
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${backendUrl}/api/auth/setup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, name: name.trim(), email: userEmail }),
      })
      if (!res.ok) {
        const err = await res.json()
        setError(err.detail || 'Setup failed')
        return
      }
      const data = await res.json()
      localStorage.setItem('flaxie_user_name', data.name)
      setStep('team')
    } catch {
      setError('Could not connect to backend')
    } finally {
      setLoading(false)
    }
  }

  async function handleTeam() {
    const uid = localStorage.getItem('flaxie_user_id')!
    const uname = localStorage.getItem('flaxie_user_name')!

    if (teamChoice === 'solo') {
      onComplete(uid, uname, null)
      return
    }

    setLoading(true)
    setError('')
    try {
      if (teamChoice === 'create') {
        const res = await fetch(`${backendUrl}/api/team/create`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: teamName.trim(), user_id: uid }),
        })
        const data = await res.json()
        localStorage.setItem('flaxie_team_id', data.team_id)
        localStorage.setItem('flaxie_invite_code', data.invite_code)
        onComplete(uid, uname, data.team_id)
      } else if (teamChoice === 'join') {
        const res = await fetch(`${backendUrl}/api/team/join`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ invite_code: inviteCode.trim().toUpperCase(), user_id: uid }),
        })
        if (!res.ok) { setError('Invalid invite code'); return }
        const data = await res.json()
        localStorage.setItem('flaxie_team_id', data.team_id)
        onComplete(uid, uname, data.team_id)
      }
    } catch {
      setError('Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  // ── Styles ─────────────────────────────────────────────────────────────────

  const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: '10px 12px',
    borderRadius: 10,
    border: '1.5px solid rgba(90, 83, 225, 0.2)',
    background: 'hsl(42, 24%, 98%)',
    fontSize: 13.5,
    color: '#1a1730',
    outline: 'none',
    fontFamily: 'Inter, system-ui, sans-serif',
    boxSizing: 'border-box',
  }

  const otpInputStyle: React.CSSProperties = {
    ...inputStyle,
    fontSize: 22,
    fontWeight: 700,
    letterSpacing: '0.3em',
    textAlign: 'center',
    fontFamily: 'IBM Plex Mono, monospace',
  }

  const btnPrimary: React.CSSProperties = {
    width: '100%',
    padding: '11px',
    borderRadius: 12,
    border: 'none',
    background: 'linear-gradient(135deg, #5A53E1, #7B75F0)',
    color: 'white',
    fontSize: 14,
    fontWeight: 600,
    cursor: loading ? 'default' : 'pointer',
    opacity: loading ? 0.7 : 1,
    transition: 'opacity 0.15s',
    fontFamily: 'Inter, system-ui, sans-serif',
  }

  const stepTitles: Record<Step, string> = {
    welcome: 'Meet Flaxie',
    email:   'Sign in',
    otp:     'Check your email',
    name:    'Nice to meet you',
    team:    'Your team',
    done:    '',
  }

  const stepSubtitles: Record<Step, string> = {
    welcome: 'Your AI accountability partner',
    email:   'No password needed',
    otp:     `Code sent to ${email}`,
    name:    'Flaxie needs to know who to root for',
    team:    'Work solo or bring your team',
    done:    '',
  }

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        background: 'hsl(42, 24%, 96%)',
        borderRadius: 20,
        overflow: 'hidden',
        boxShadow: '0 24px 64px rgba(74, 66, 216, 0.22), 0 4px 16px rgba(0,0,0,0.12)',
        border: '1px solid rgba(90, 83, 225, 0.14)',
        fontFamily: 'Inter, system-ui, sans-serif',
      }}
    >
      {/* Purple header */}
      <div
        style={{
          background: 'linear-gradient(135deg, #4A42D8, #6B63E8)',
          padding: '28px 24px 24px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <motion.div
          animate={{ scale: [1, 1.05, 1] }}
          transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
        >
          <FlaxieBig />
        </motion.div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'white', marginBottom: 4 }}>
            {stepTitles[step]}
          </div>
          <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.75)' }}>
            {stepSubtitles[step]}
          </div>
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, padding: '24px', overflowY: 'auto' }}>
        <AnimatePresence mode="wait">
          {step === 'welcome' && (
            <motion.div
              key="welcome"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
            >
              <p style={{ fontSize: 14, lineHeight: 1.65, color: '#4a4760', marginBottom: 24 }}>
                Flaxie lives on your desktop. It knows what you're working on, watches the clock, and nudges you — warmly — when things need attention.
              </p>
              <p style={{ fontSize: 14, lineHeight: 1.65, color: '#4a4760', marginBottom: 32 }}>
                No forms. No standups. Just an AI that actually pays attention.
              </p>
              <button style={btnPrimary} onClick={() => setStep('email')}>
                Get started →
              </button>
            </motion.div>
          )}

          {step === 'email' && (
            <motion.div
              key="email"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
            >
              <p style={{ fontSize: 13, color: '#6b6890', marginBottom: 4 }}>
                We'll send an 8-digit code to your email. No password required.
              </p>
              <input
                style={inputStyle}
                placeholder="you@company.com"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSendOtp()}
                autoFocus
              />
              {error && <div style={{ fontSize: 12, color: '#e74c3c' }}>{error}</div>}
              <button
                style={{ ...btnPrimary, marginTop: 4 }}
                onClick={handleSendOtp}
                disabled={loading || !email.trim() || !supabase}
              >
                {loading ? 'Sending...' : 'Send code →'}
              </button>
              {!supabase && (
                <div style={{ fontSize: 11, color: '#e74c3c', textAlign: 'center' }}>
                  Supabase not configured — check SUPABASE_URL and SUPABASE_ANON_KEY
                </div>
              )}
            </motion.div>
          )}

          {step === 'otp' && (
            <motion.div
              key="otp"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
            >
              <p style={{ fontSize: 13, color: '#6b6890', marginBottom: 4 }}>
                Enter the 8-digit code from your email.
              </p>
              <input
                style={otpInputStyle}
                placeholder="00000000"
                type="text"
                inputMode="numeric"
                maxLength={8}
                value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 8))}
                onKeyDown={(e) => e.key === 'Enter' && otp.length === 8 && handleVerifyOtp()}
                autoFocus
              />
              {error && <div style={{ fontSize: 12, color: '#e74c3c' }}>{error}</div>}
              <button
                style={{ ...btnPrimary, marginTop: 4 }}
                onClick={handleVerifyOtp}
                disabled={loading || otp.length < 8}
              >
                {loading ? 'Verifying...' : 'Verify →'}
              </button>

              {/* Resend */}
              <div style={{ textAlign: 'center', marginTop: 4 }}>
                {resendCooldown > 0 ? (
                  <span style={{ fontSize: 12, color: '#9B97CC' }}>
                    Resend in {resendCooldown}s
                  </span>
                ) : (
                  <button
                    style={{
                      background: 'none', border: 'none', cursor: 'pointer',
                      fontSize: 12, color: '#5A53E1', textDecoration: 'underline',
                    }}
                    onClick={handleSendOtp}
                  >
                    Resend code
                  </button>
                )}
                <span style={{ fontSize: 12, color: '#9B97CC', marginLeft: 12 }}>·</span>
                <button
                  style={{
                    background: 'none', border: 'none', cursor: 'pointer',
                    fontSize: 12, color: '#9B97CC', marginLeft: 12,
                  }}
                  onClick={() => { setStep('email'); setOtp(''); setError('') }}
                >
                  Change email
                </button>
              </div>
            </motion.div>
          )}

          {step === 'name' && (
            <motion.div
              key="name"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
            >
              <p style={{ fontSize: 13, color: '#6b6890', marginBottom: 4 }}>
                What should Flaxie call you?
              </p>
              <input
                style={inputStyle}
                placeholder="Your name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSetupProfile()}
                autoFocus
              />
              {error && <div style={{ fontSize: 12, color: '#e74c3c' }}>{error}</div>}
              <button
                style={{ ...btnPrimary, marginTop: 4 }}
                onClick={handleSetupProfile}
                disabled={loading || !name.trim()}
              >
                {loading ? 'Setting up...' : 'Continue →'}
              </button>
            </motion.div>
          )}

          {step === 'team' && (
            <motion.div
              key="team"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              style={{ display: 'flex', flexDirection: 'column', gap: 10 }}
            >
              {(['solo', 'create', 'join'] as const).map((opt) => (
                <button
                  key={opt}
                  onClick={() => setTeamChoice(opt)}
                  style={{
                    padding: '13px 16px',
                    borderRadius: 12,
                    border: `2px solid ${teamChoice === opt ? '#5A53E1' : 'rgba(90, 83, 225, 0.15)'}`,
                    background: teamChoice === opt ? 'rgba(90, 83, 225, 0.08)' : 'white',
                    cursor: 'pointer',
                    textAlign: 'left',
                    transition: 'all 0.15s',
                  }}
                >
                  <div style={{ fontSize: 13.5, fontWeight: 600, color: '#1a1730', marginBottom: 2 }}>
                    {opt === 'solo' ? '✦ Just me' : opt === 'create' ? '+ Create a team' : '→ Join a team'}
                  </div>
                  <div style={{ fontSize: 11.5, color: '#9B97CC' }}>
                    {opt === 'solo'
                      ? 'Solo accountability mode — your tasks, your nudges'
                      : opt === 'create'
                        ? 'Invite teammates and see what everyone is working on'
                        : 'Enter an invite code from your team admin'}
                  </div>
                </button>
              ))}

              {teamChoice === 'create' && (
                <input
                  style={{ ...inputStyle, marginTop: 4 }}
                  placeholder="Team name (e.g. Acme Squad)"
                  value={teamName}
                  onChange={(e) => setTeamName(e.target.value)}
                  autoFocus
                />
              )}

              {teamChoice === 'join' && (
                <input
                  style={{
                    ...inputStyle, marginTop: 4,
                    fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '0.1em',
                  }}
                  placeholder="INVITE CODE"
                  value={inviteCode}
                  onChange={(e) => setInviteCode(e.target.value.toUpperCase())}
                  autoFocus
                />
              )}

              {error && <div style={{ fontSize: 12, color: '#e74c3c', textAlign: 'center' }}>{error}</div>}

              <button
                style={{ ...btnPrimary, marginTop: 8 }}
                onClick={handleTeam}
                disabled={
                  loading ||
                  !teamChoice ||
                  (teamChoice === 'create' && !teamName.trim()) ||
                  (teamChoice === 'join' && inviteCode.length < 6)
                }
              >
                {loading ? 'Setting up...' : 'Start using Flaxie →'}
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
