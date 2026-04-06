import { motion } from 'framer-motion'
import { useState } from 'react'

interface Props {
  backendUrl: string
  onComplete: (userId: string, userName: string, teamId: string | null) => void
}

type Step = 'welcome' | 'name' | 'team' | 'done'

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
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [teamChoice, setTeamChoice] = useState<'solo' | 'create' | 'join' | null>(null)
  const [teamName, setTeamName] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleRegister() {
    if (!name.trim() || !email.trim() || !password.trim()) return
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${backendUrl}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), email: email.trim(), password }),
      })
      if (!res.ok) {
        const err = await res.json()
        setError(err.detail || 'Registration failed')
        return
      }
      const data = await res.json()
      localStorage.setItem('flaxie_user_id', data.user_id)
      localStorage.setItem('flaxie_user_name', data.name)
      localStorage.setItem('flaxie_token', data.token)
      setStep('team')
    } catch {
      setError('Could not connect to backend')
    } finally {
      setLoading(false)
    }
  }

  async function handleTeam() {
    const userId = localStorage.getItem('flaxie_user_id')!
    const userName = localStorage.getItem('flaxie_user_name')!

    if (teamChoice === 'solo') {
      onComplete(userId, userName, null)
      return
    }

    setLoading(true)
    setError('')
    try {
      if (teamChoice === 'create') {
        const res = await fetch(`${backendUrl}/api/team/create`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: teamName.trim(), user_id: userId }),
        })
        const data = await res.json()
        localStorage.setItem('flaxie_team_id', data.team_id)
        localStorage.setItem('flaxie_invite_code', data.invite_code)
        onComplete(userId, userName, data.team_id)
      } else if (teamChoice === 'join') {
        const res = await fetch(`${backendUrl}/api/team/join`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ invite_code: inviteCode.trim().toUpperCase(), user_id: userId }),
        })
        if (!res.ok) {
          setError('Invalid invite code')
          return
        }
        const data = await res.json()
        localStorage.setItem('flaxie_team_id', data.team_id)
        onComplete(userId, userName, data.team_id)
      }
    } catch {
      setError('Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  const inputStyle = {
    width: '100%',
    padding: '10px 12px',
    borderRadius: 10,
    border: '1.5px solid rgba(90, 83, 225, 0.2)',
    background: 'hsl(42, 24%, 98%)',
    fontSize: 13.5,
    color: '#1a1730',
    outline: 'none',
    fontFamily: 'Inter, system-ui, sans-serif',
    boxSizing: 'border-box' as const,
  }

  const btnPrimary = {
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
            {step === 'welcome' ? 'Meet Flaxie' : step === 'name' ? 'Who are you?' : "Your team"}
          </div>
          <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.75)' }}>
            {step === 'welcome'
              ? 'Your AI accountability partner'
              : step === 'name'
                ? "Flaxie needs to know who to root for"
                : 'Work solo or bring your team'}
          </div>
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, padding: '24px', overflowY: 'auto' }}>
        {step === 'welcome' && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
            <p style={{ fontSize: 14, lineHeight: 1.65, color: '#4a4760', marginBottom: 24 }}>
              Flaxie lives on your desktop. It knows what you're working on, watches the clock, and nudges you — warmly — when things need attention.
            </p>
            <p style={{ fontSize: 14, lineHeight: 1.65, color: '#4a4760', marginBottom: 32 }}>
              No forms. No standups. Just an AI that actually pays attention.
            </p>
            <button style={btnPrimary} onClick={() => setStep('name')}>
              Let's go →
            </button>
          </motion.div>
        )}

        {step === 'name' && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
          >
            <input
              style={inputStyle}
              placeholder="Your name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
            <input
              style={inputStyle}
              placeholder="Email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <input
              style={inputStyle}
              placeholder="Password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleRegister()}
            />
            {error && (
              <div style={{ fontSize: 12, color: '#e74c3c', textAlign: 'center' }}>{error}</div>
            )}
            <button
              style={{ ...btnPrimary, marginTop: 8 }}
              onClick={handleRegister}
              disabled={loading}
            >
              {loading ? 'Setting up...' : 'Continue →'}
            </button>
          </motion.div>
        )}

        {step === 'team' && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            style={{ display: 'flex', flexDirection: 'column', gap: 10 }}
          >
            {/* Solo option */}
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
                style={{ ...inputStyle, marginTop: 4, fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '0.1em' }}
                placeholder="INVITE CODE"
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value.toUpperCase())}
                autoFocus
              />
            )}

            {error && (
              <div style={{ fontSize: 12, color: '#e74c3c', textAlign: 'center' }}>{error}</div>
            )}

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
      </div>
    </div>
  )
}
