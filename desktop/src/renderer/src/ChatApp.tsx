import { useEffect, useRef, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import MessageBubble from './chat/MessageBubble'
import TaskChip from './chat/TaskChip'
import Onboarding from './chat/Onboarding'
import { useChatStore } from './store/chatStore'
import type { Message } from './chat/MessageBubble'

declare global {
  interface Window {
    flaxie?: {
      getBackendUrl: () => Promise<string>
      closeChat: () => void
    }
  }
}

// ── Icons ─────────────────────────────────────────────────────────────────────

function FlaxieIcon({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" fill="none">
      <defs>
        <linearGradient id="fg" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#4A42D8" />
          <stop offset="100%" stopColor="#6B63E8" />
        </linearGradient>
      </defs>
      <circle cx="50" cy="50" r="46" fill="url(#fg)" />
      <g fill="none" stroke="white" strokeWidth="2.5">
        {[0, 72, 144, 216, 288].map((r, i) => (
          <ellipse key={i} cx="50" cy="28" rx="10" ry="16" transform={`rotate(${r}, 50, 50)`} />
        ))}
      </g>
      <circle cx="50" cy="50" r="8" fill="white" />
      <circle cx="50" cy="50" r="4" fill="url(#fg)" />
    </svg>
  )
}

function SendIcon({ active }: { active: boolean }) {
  return (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
      <path d="M1.5 7.5L13.5 1.5L7.5 13.5L6.5 8.5L1.5 7.5Z"
        fill={active ? 'white' : '#A29BFE'}
        stroke={active ? 'white' : '#A29BFE'}
        strokeWidth="0.5" strokeLinejoin="round"
      />
    </svg>
  )
}

// ── Typing indicator ──────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14, paddingLeft: 33 }}
    >
      <div style={{
        display: 'flex', gap: 4, alignItems: 'center',
        background: 'white', padding: '8px 12px', borderRadius: '4px 16px 16px 16px',
        border: '1px solid rgba(90,83,225,0.1)', boxShadow: '0 1px 6px rgba(0,0,0,0.06)',
      }}>
        {[0, 0.18, 0.36].map((delay, i) => (
          <motion.div key={i}
            style={{ width: 5, height: 5, borderRadius: '50%', background: '#A29BFE' }}
            animate={{ scale: [1, 1.5, 1], opacity: [0.4, 1, 0.4] }}
            transition={{ duration: 0.7, repeat: Infinity, delay }}
          />
        ))}
      </div>
    </motion.div>
  )
}

// ── Agent status bar ──────────────────────────────────────────────────────────

function AgentStatusBar({ taskCount }: { taskCount: number }) {
  const [pulse, setPulse] = useState(false)

  useEffect(() => {
    const t = setInterval(() => { setPulse(true); setTimeout(() => setPulse(false), 600) }, 8000)
    return () => clearInterval(t)
  }, [])

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 6,
      padding: '5px 14px',
      background: 'rgba(90,83,225,0.04)',
      borderBottom: '1px solid rgba(90,83,225,0.07)',
      fontSize: 10.5, color: '#9B97CC',
      fontFamily: 'IBM Plex Mono, monospace',
    }}>
      <motion.div
        animate={pulse ? { scale: [1, 1.6, 1] } : { scale: 1 }}
        transition={{ duration: 0.5 }}
        style={{ width: 6, height: 6, borderRadius: '50%', background: '#2ED573', flexShrink: 0 }}
      />
      <span>
        Agent active · watching {taskCount} task{taskCount !== 1 ? 's' : ''}
      </span>
    </div>
  )
}

// ── Add task inline ───────────────────────────────────────────────────────────

function QuickAddTask({ onAdd }: { onAdd: (title: string) => void }) {
  const [value, setValue] = useState('')
  const [active, setActive] = useState(false)

  function submit() {
    if (!value.trim()) return
    onAdd(value.trim())
    setValue('')
    setActive(false)
  }

  return (
    <div style={{ padding: '6px 12px 10px' }}>
      {active ? (
        <div style={{
          display: 'flex', gap: 6, alignItems: 'center',
          background: 'white', borderRadius: 10, padding: '6px 10px',
          border: '1.5px solid rgba(90,83,225,0.3)',
        }}>
          <input
            autoFocus
            value={value}
            onChange={e => setValue(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') submit(); if (e.key === 'Escape') setActive(false) }}
            placeholder="Task title..."
            style={{
              flex: 1, border: 'none', outline: 'none', background: 'none',
              fontSize: 13, color: '#1a1730', fontFamily: 'inherit',
            }}
          />
          <button onClick={submit} style={{
            padding: '3px 10px', borderRadius: 7, border: 'none',
            background: '#5A53E1', color: 'white', fontSize: 11,
            fontWeight: 600, cursor: 'pointer',
          }}>Add</button>
          <button onClick={() => setActive(false)} style={{
            border: 'none', background: 'none', color: '#9B97CC',
            cursor: 'pointer', fontSize: 14, padding: '0 2px',
          }}>✕</button>
        </div>
      ) : (
        <button onClick={() => setActive(true)} style={{
          width: '100%', padding: '7px 10px', borderRadius: 10,
          border: '1.5px dashed rgba(90,83,225,0.2)', background: 'none',
          color: '#9B97CC', fontSize: 12, cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5,
          fontFamily: 'inherit', transition: 'all 0.15s',
        }}>
          <span style={{ fontSize: 14, lineHeight: 1 }}>+</span> Add task
        </button>
      )}
    </div>
  )
}

// ── Main ChatApp ──────────────────────────────────────────────────────────────

export default function ChatApp() {
  const { messages, tasks, isLoading, backendUrl, addMessage, setTasks, updateTaskStatus, setLoading, setBackendUrl } =
    useChatStore()
  const [input, setInput] = useState('')
  const [activeTab, setActiveTab] = useState<'chat' | 'tasks'>('chat')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const greetingShown = useRef(false)
  const [userId, setUserId] = useState(() => localStorage.getItem('flaxie_user_id') || '')
  const [userName, setUserName] = useState(() => localStorage.getItem('flaxie_user_name') || '')
  const isOnboarding = !userId

  // Init backend URL + tell main process the real user ID for WebSocket
  useEffect(() => {
    if (window.flaxie) {
      window.flaxie.getBackendUrl().then(setBackendUrl)
      if (userId) (window.flaxie as any).setUserId(userId)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Load tasks when ready
  useEffect(() => {
    if (!backendUrl || !userId) return
    fetch(`${backendUrl}/api/tasks?user_id=${userId}`)
      .then(r => r.json()).then(setTasks).catch(() => {})
  }, [backendUrl, userId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Greeting — once per session (not every window open)
  useEffect(() => {
    if (!userId || !backendUrl || greetingShown.current || messages.length > 0) return
    greetingShown.current = true

    const firstName = userName ? userName.split(' ')[0] : ''
    fetch(`${backendUrl}/api/chat/greeting?user_id=${userId}&user_name=${encodeURIComponent(userName)}`)
      .then(r => r.json())
      .then(data => {
        addMessage({
          id: 'welcome',
          role: 'assistant',
          content: data.message || `Hey${firstName ? `, ${firstName}` : ''}! What are you working on?`,
          timestamp: new Date(),
        })
      })
      .catch(() => {
        const h = new Date().getHours()
        addMessage({
          id: 'welcome', role: 'assistant', timestamp: new Date(),
          content: h < 12 ? `Morning${firstName ? `, ${firstName}` : ''}! What's on the list?`
            : h < 17 ? `Hey${firstName ? `, ${firstName}` : ''}! What are you working on?`
            : `Evening${firstName ? `, ${firstName}` : ''}! How's the day going?`,
        })
      })
  }, [userId, backendUrl]) // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  const sendMessage = useCallback(async () => {
    const text = input.trim()
    if (!text || isLoading) return

    const userMsg: Message = { id: `u_${Date.now()}`, role: 'user', content: text, timestamp: new Date() }
    addMessage(userMsg)
    setInput('')
    setLoading(true)

    try {
      const res = await fetch(`${backendUrl}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text, user_id: userId, user_name: userName,
          history: messages.slice(-12).map(m => ({ role: m.role, content: m.content })),
        }),
      })
      const data = await res.json()
      addMessage({ id: `a_${Date.now()}`, role: 'assistant', content: data.reply, timestamp: new Date(), task_refs: data.task_refs })
      if (data.tasks_changed) {
        const tr = await fetch(`${backendUrl}/api/tasks?user_id=${userId}`)
        setTasks(await tr.json())
      }
    } catch (err) {
      addMessage({ id: `err_${Date.now()}`, role: 'assistant', timestamp: new Date(),
        content: `Couldn't reach backend — is it running?` })
    } finally {
      setLoading(false)
    }
  }, [input, isLoading, backendUrl, userId, userName, messages, addMessage, setLoading, setTasks])

  async function markTaskDone(taskId: string) {
    updateTaskStatus(taskId, 'done')
    try {
      await fetch(`${backendUrl}/api/tasks/${taskId}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'done' }),
      })
      const remaining = tasks.filter(t => t.status !== 'done' && t.id !== taskId).length
      addMessage({
        id: `done_${Date.now()}`, role: 'assistant', timestamp: new Date(),
        content: remaining === 0
          ? `That's it — all done! Nice work 🎉`
          : `Marked done. ${remaining} task${remaining !== 1 ? 's' : ''} still open.`,
      })
      setActiveTab('chat')
    } catch { updateTaskStatus(taskId, 'open') }
  }

  async function quickAddTask(title: string) {
    try {
      const res = await fetch(`${backendUrl}/api/tasks`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, user_id: userId, status: 'open' }),
      })
      const t = await res.json()
      const tr = await fetch(`${backendUrl}/api/tasks?user_id=${userId}`)
      setTasks(await tr.json())
      addMessage({ id: `add_${Date.now()}`, role: 'assistant', timestamp: new Date(),
        content: `Added "${t.title}" to your list. I'll keep an eye on it.`,
        task_refs: [{ id: t.id, title: t.title }],
      })
    } catch {}
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  const openTasks = tasks.filter(t => t.status !== 'done')
  const doneTasks = tasks.filter(t => t.status === 'done')
  const urgentTasks = openTasks.filter(t => {
    if (!t.deadline) return false
    const h = (new Date(t.deadline).getTime() - Date.now()) / 3600000
    return h < 24
  })

  if (isOnboarding) {
    return (
      <Onboarding
        backendUrl={backendUrl}
        onComplete={(uid, uname) => {
          setUserId(uid)
          setUserName(uname)
          if (window.flaxie) (window.flaxie as any).setUserId(uid)
        }}
      />
    )
  }

  return (
    <div style={{
      width: '100%', height: '100%',
      display: 'flex', flexDirection: 'column',
      background: '#F8F7FE',
      borderRadius: 18,
      overflow: 'hidden',
      boxShadow: '0 20px 60px rgba(74,66,216,0.2), 0 4px 16px rgba(0,0,0,0.1)',
      border: '1px solid rgba(90,83,225,0.12)',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Inter", system-ui, sans-serif',
    }}>

      {/* ── Header ── */}
      <div style={{
        padding: '13px 14px 10px',
        background: 'white',
        borderBottom: '1px solid rgba(90,83,225,0.08)',
        display: 'flex', alignItems: 'center', gap: 10,
        WebkitAppRegion: 'drag' as never,
      }}>
        <FlaxieIcon size={30} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#1a1730', letterSpacing: '-0.01em' }}>
            Flaxie
          </div>
          <div style={{ fontSize: 11, color: urgentTasks.length > 0 ? '#E67E22' : '#9B97CC', marginTop: 0.5 }}>
            {urgentTasks.length > 0
              ? `⚠ ${urgentTasks.length} task${urgentTasks.length > 1 ? 's' : ''} due today`
              : openTasks.length > 0
                ? `${openTasks.length} open task${openTasks.length !== 1 ? 's' : ''}`
                : 'All caught up ✓'}
          </div>
        </div>
        <button
          onClick={() => window.flaxie?.closeChat()}
          style={{
            width: 26, height: 26, borderRadius: 8, border: 'none',
            background: 'rgba(90,83,225,0.07)', cursor: 'pointer',
            color: '#9B97CC', fontSize: 12,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            WebkitAppRegion: 'no-drag' as never,
            transition: 'background 0.15s',
          }}
        >
          ✕
        </button>
      </div>

      {/* ── Agent status ── */}
      <AgentStatusBar taskCount={openTasks.length} />

      {/* ── Tabs ── */}
      <div style={{
        display: 'flex', background: 'white',
        borderBottom: '1px solid rgba(90,83,225,0.08)',
        padding: '0 14px',
      }}>
        {(['chat', 'tasks'] as const).map(tab => (
          <button key={tab} onClick={() => setActiveTab(tab)} style={{
            padding: '8px 14px 9px', fontSize: 12, fontWeight: 600,
            cursor: 'pointer', border: 'none', background: 'none',
            color: activeTab === tab ? '#5A53E1' : '#9B97CC',
            borderBottom: activeTab === tab ? '2px solid #5A53E1' : '2px solid transparent',
            transition: 'all 0.15s', textTransform: 'capitalize', letterSpacing: '0.01em',
          }}>
            {tab}
            {tab === 'tasks' && openTasks.length > 0 && (
              <span style={{
                marginLeft: 5, background: '#5A53E1', color: 'white',
                borderRadius: 10, fontSize: 9, padding: '1px 5px', fontWeight: 700,
              }}>
                {openTasks.length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── Content ── */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <AnimatePresence mode="wait">

          {/* Chat tab */}
          {activeTab === 'chat' && (
            <motion.div key="chat"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              style={{ flex: 1, overflowY: 'auto', padding: '16px 12px 8px' }}
            >
              {messages.length === 0 && (
                <div style={{ textAlign: 'center', paddingTop: 40, color: '#C3BFF7' }}>
                  <div style={{ fontSize: 28, marginBottom: 8 }}>✦</div>
                  <div style={{ fontSize: 12 }}>Flaxie is ready</div>
                </div>
              )}
              {messages.map((msg, i) => (
                <MessageBubble key={msg.id} message={msg} isLatest={i === messages.length - 1} />
              ))}
              <AnimatePresence>{isLoading && <TypingIndicator />}</AnimatePresence>
              <div ref={messagesEndRef} />
            </motion.div>
          )}

          {/* Tasks tab */}
          {activeTab === 'tasks' && (
            <motion.div key="tasks"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}
            >
              <div style={{ flex: 1, padding: '10px 12px 4px' }}>
                {openTasks.length === 0 && doneTasks.length === 0 ? (
                  <div style={{ textAlign: 'center', color: '#9B97CC', marginTop: 40 }}>
                    <div style={{ fontSize: 28, marginBottom: 8 }}>✦</div>
                    <div style={{ fontSize: 13 }}>No tasks yet</div>
                    <div style={{ fontSize: 11, marginTop: 4, color: '#C3BFF7' }}>Add one below or tell Flaxie in chat</div>
                  </div>
                ) : (
                  <>
                    {urgentTasks.length > 0 && (
                      <div style={{ marginBottom: 14 }}>
                        <SectionLabel color="#E67E22">Urgent · {urgentTasks.length}</SectionLabel>
                        {urgentTasks.map(t => <TaskChip key={t.id} task={t} onDone={markTaskDone} />)}
                      </div>
                    )}
                    {openTasks.filter(t => !urgentTasks.includes(t)).length > 0 && (
                      <div style={{ marginBottom: 14 }}>
                        <SectionLabel color="#5A53E1">
                          Open · {openTasks.filter(t => !urgentTasks.includes(t)).length}
                        </SectionLabel>
                        {openTasks.filter(t => !urgentTasks.includes(t)).map(t =>
                          <TaskChip key={t.id} task={t} onDone={markTaskDone} />
                        )}
                      </div>
                    )}
                    {doneTasks.length > 0 && (
                      <div>
                        <SectionLabel color="#9B97CC">Done · {doneTasks.length}</SectionLabel>
                        {doneTasks.slice(0, 5).map(t => <TaskChip key={t.id} task={t} />)}
                      </div>
                    )}
                  </>
                )}
              </div>
              <QuickAddTask onAdd={quickAddTask} />
            </motion.div>
          )}

        </AnimatePresence>
      </div>

      {/* ── Input ── */}
      {activeTab === 'chat' && (
        <div style={{ padding: '8px 12px 10px', background: 'white', borderTop: '1px solid rgba(90,83,225,0.08)' }}>
          <div style={{
            display: 'flex', alignItems: 'flex-end', gap: 8,
            background: '#F8F7FE', borderRadius: 14, padding: '8px 10px',
            border: '1.5px solid rgba(90,83,225,0.15)',
          }}>
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Tell Flaxie what you're working on..."
              disabled={isLoading}
              rows={1}
              style={{
                flex: 1, background: 'none', border: 'none', outline: 'none',
                resize: 'none', fontSize: 13.5, lineHeight: 1.45,
                color: '#1a1730', fontFamily: 'inherit',
                maxHeight: 80, overflowY: 'auto',
              }}
            />
            <button
              onClick={sendMessage}
              disabled={!input.trim() || isLoading}
              style={{
                width: 30, height: 30, borderRadius: 10, border: 'none',
                background: !input.trim() || isLoading ? '#EEEDff' : 'linear-gradient(135deg, #5A53E1, #7B75F0)',
                cursor: !input.trim() || isLoading ? 'default' : 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'all 0.15s', flexShrink: 0,
              }}
            >
              <SendIcon active={!!input.trim() && !isLoading} />
            </button>
          </div>
          <div style={{ fontSize: 10, color: '#C3BFF7', marginTop: 4, textAlign: 'center' }}>
            Enter to send · Shift+Enter for new line
          </div>
        </div>
      )}
    </div>
  )
}

function SectionLabel({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <div style={{
      fontSize: 10, fontWeight: 700, color, letterSpacing: '0.08em',
      textTransform: 'uppercase', marginBottom: 6,
      fontFamily: 'IBM Plex Mono, monospace',
    }}>
      {children}
    </div>
  )
}
