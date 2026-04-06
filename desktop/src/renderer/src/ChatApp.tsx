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
  const [activeTab, setActiveTab] = useState<'chat' | 'tasks' | 'settings'>('chat')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const greetingShown = useRef(false)
  const [userId, setUserId] = useState(() => localStorage.getItem('flaxie_user_id') || '')
  const [userName, setUserName] = useState(() => localStorage.getItem('flaxie_user_name') || '')
  const [teamMembers, setTeamMembers] = useState<{user_id: string, name: string}[]>([])
  const [assigningTaskId, setAssigningTaskId] = useState<string | null>(null)
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

  // Load team members for assignment UI
  useEffect(() => {
    if (!backendUrl || !userId) return
    const teamId = localStorage.getItem('flaxie_team_id')
    if (!teamId) return
    fetch(`${backendUrl}/api/team/overview?team_id=${teamId}`)
      .then(r => r.json())
      .then(d => setTeamMembers((d.members || []).filter((m: any) => m.user_id !== userId)))
      .catch(() => {})
  }, [backendUrl, userId]) // eslint-disable-line

  // Pick up nudge context whenever the chat window gains focus
  // (notification button stores context in localStorage then opens chat)
  const isLoadingRef = useRef(isLoading)
  useEffect(() => { isLoadingRef.current = isLoading }, [isLoading])

  useEffect(() => {
    if (!backendUrl || !userId) return

    async function handleNudgeContext() {
      const raw = localStorage.getItem('flaxie_nudge_context')
      if (!raw || isLoadingRef.current) return
      localStorage.removeItem('flaxie_nudge_context')

      let userText = raw
      let systemHint = ''
      try {
        const ctx = JSON.parse(raw)
        userText = ctx.taskTitle ? `${ctx.action} (re: "${ctx.taskTitle}")` : ctx.action
        systemHint = ctx.nudgeMessage || ''
      } catch { /* raw string fallback */ }

      setActiveTab('chat')
      addMessage({ id: `n_${Date.now()}`, role: 'user', content: userText, timestamp: new Date() })
      setLoading(true)
      try {
        const res = await fetch(`${backendUrl}/api/chat`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: userText,
            user_id: userId, user_name: userName,
            history: useChatStore.getState().messages.slice(-12).map(m => ({ role: m.role, content: m.content })),
            nudge_context: systemHint,
          }),
        })
        const data = await res.json()
        addMessage({ id: `nr_${Date.now()}`, role: 'assistant', content: data.reply, timestamp: new Date() })
      } catch {} finally { setLoading(false) }
    }

    window.addEventListener('focus', handleNudgeContext)
    // Also check immediately — chat may already be focused when context is set
    handleNudgeContext()
    return () => window.removeEventListener('focus', handleNudgeContext)
  }, [backendUrl, userId]) // eslint-disable-line

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
    if (inputRef.current) inputRef.current.style.height = '22px'
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

  async function archiveDoneTasks() {
    const done = tasks.filter(t => t.status === 'done')
    await Promise.all(done.map(t =>
      fetch(`${backendUrl}/api/tasks/${t.id}`, { method: 'DELETE' }).catch(() => {})
    ))
    const tr = await fetch(`${backendUrl}/api/tasks?user_id=${userId}`)
    setTasks(await tr.json())
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

  async function assignTask(taskId: string, assigneeId: string) {
    try {
      await fetch(`${backendUrl}/api/tasks/${taskId}/assign`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ assignee_id: assigneeId, owner_id: userId }),
      })
      const tr = await fetch(`${backendUrl}/api/tasks?user_id=${userId}`)
      setTasks(await tr.json())
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

  // Team task groups
  const assignedToMeTasks = openTasks.filter(t => t.assignee_id === userId && t.owner_id !== userId)
  const myOwnTasks = openTasks.filter(t => t.owner_id === userId && t.assignee_id === userId)
  const watchingTasks = openTasks.filter(t => t.owner_id === userId && t.assignee_id !== userId)
  const hasTeamTasks = assignedToMeTasks.length > 0 || watchingTasks.length > 0

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
        {/* New chat */}
        <button
          onClick={() => {
            useChatStore.getState().clearMessages()
            greetingShown.current = false
          }}
          title="New chat"
          style={{
            width: 26, height: 26, borderRadius: 8, border: 'none',
            background: 'rgba(90,83,225,0.07)', cursor: 'pointer',
            color: '#9B97CC', fontSize: 13,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            WebkitAppRegion: 'no-drag' as never,
            transition: 'background 0.15s',
          }}
        >
          ↺
        </button>
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
        {(['chat', 'tasks', 'settings'] as const).map(tab => (
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

          {/* Settings tab */}
          {activeTab === 'settings' && (
            <motion.div key="settings"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              style={{ flex: 1, overflowY: 'auto' }}
            >
              <SettingsPanel
                userId={userId}
                userName={userName}
                backendUrl={backendUrl}
                onSignOut={() => {
                  localStorage.removeItem('flaxie_user_id')
                  localStorage.removeItem('flaxie_user_name')
                  window.location.reload()
                }}
                onTeamJoined={(tid, tname) => {
                  localStorage.setItem('flaxie_team_id', tid)
                  localStorage.setItem('flaxie_team_name', tname)
                }}
              />
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
                ) : hasTeamTasks ? (
                  <>
                    {assignedToMeTasks.length > 0 && (
                      <div style={{ marginBottom: 14 }}>
                        <SectionLabel color="#E67E22">Assigned to me · {assignedToMeTasks.length}</SectionLabel>
                        {assignedToMeTasks.map(t => (
                          <TaskChip key={t.id} task={t} onDone={markTaskDone}
                            currentUserId={userId}
                            teamMembers={teamMembers}
                          />
                        ))}
                      </div>
                    )}
                    {myOwnTasks.length > 0 && (
                      <div style={{ marginBottom: 14 }}>
                        <SectionLabel color="#5A53E1">Open · {myOwnTasks.length}</SectionLabel>
                        {myOwnTasks.map(t => (
                          <TaskChip key={t.id} task={t} onDone={markTaskDone}
                            currentUserId={userId}
                            teamMembers={teamMembers}
                            onAssign={assignTask}
                            assigningTaskId={assigningTaskId}
                            setAssigningTaskId={setAssigningTaskId}
                          />
                        ))}
                      </div>
                    )}
                    {watchingTasks.length > 0 && (
                      <div style={{ marginBottom: 14 }}>
                        <SectionLabel color="#A29BFE">I'm watching · {watchingTasks.length}</SectionLabel>
                        {watchingTasks.map(t => (
                          <TaskChip key={t.id} task={t}
                            currentUserId={userId}
                            teamMembers={teamMembers}
                            onAssign={assignTask}
                            assigningTaskId={assigningTaskId}
                            setAssigningTaskId={setAssigningTaskId}
                          />
                        ))}
                      </div>
                    )}
                    {doneTasks.length > 0 && (
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                          <SectionLabel color="#9B97CC" noMargin>Done · {doneTasks.length}</SectionLabel>
                          <button onClick={archiveDoneTasks} style={{
                            fontSize: 10, padding: '2px 8px', borderRadius: 6, border: 'none',
                            background: 'rgba(0,0,0,0.05)', color: '#9B97CC', cursor: 'pointer',
                            fontFamily: 'inherit', fontWeight: 500,
                          }}>Archive all</button>
                        </div>
                        {doneTasks.slice(0, 5).map(t => <TaskChip key={t.id} task={t} currentUserId={userId} />)}
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    {urgentTasks.length > 0 && (
                      <div style={{ marginBottom: 14 }}>
                        <SectionLabel color="#E67E22">Urgent · {urgentTasks.length}</SectionLabel>
                        {urgentTasks.map(t => (
                          <TaskChip key={t.id} task={t} onDone={markTaskDone}
                            currentUserId={userId}
                            teamMembers={teamMembers}
                            onAssign={assignTask}
                            assigningTaskId={assigningTaskId}
                            setAssigningTaskId={setAssigningTaskId}
                          />
                        ))}
                      </div>
                    )}
                    {openTasks.filter(t => !urgentTasks.includes(t)).length > 0 && (
                      <div style={{ marginBottom: 14 }}>
                        <SectionLabel color="#5A53E1">
                          Open · {openTasks.filter(t => !urgentTasks.includes(t)).length}
                        </SectionLabel>
                        {openTasks.filter(t => !urgentTasks.includes(t)).map(t => (
                          <TaskChip key={t.id} task={t} onDone={markTaskDone}
                            currentUserId={userId}
                            teamMembers={teamMembers}
                            onAssign={assignTask}
                            assigningTaskId={assigningTaskId}
                            setAssigningTaskId={setAssigningTaskId}
                          />
                        ))}
                      </div>
                    )}
                    {doneTasks.length > 0 && (
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                          <SectionLabel color="#9B97CC" noMargin>Done · {doneTasks.length}</SectionLabel>
                          <button onClick={archiveDoneTasks} style={{
                            fontSize: 10, padding: '2px 8px', borderRadius: 6, border: 'none',
                            background: 'rgba(0,0,0,0.05)', color: '#9B97CC', cursor: 'pointer',
                            fontFamily: 'inherit', fontWeight: 500,
                          }}>Archive all</button>
                        </div>
                        {doneTasks.slice(0, 5).map(t => <TaskChip key={t.id} task={t} currentUserId={userId} />)}
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
              onChange={e => {
                setInput(e.target.value)
                e.target.style.height = 'auto'
                e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px'
              }}
              onKeyDown={handleKeyDown}
              placeholder="Tell Flaxie what you're working on..."
              disabled={isLoading}
              rows={1}
              style={{
                flex: 1, background: 'none', border: 'none', outline: 'none',
                resize: 'none', fontSize: 13.5, lineHeight: 1.45,
                color: '#1a1730', fontFamily: 'inherit',
                height: 22, minHeight: 22, maxHeight: 120, overflowY: 'auto',
                transition: 'height 0.1s ease',
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

// ── Settings Panel ────────────────────────────────────────────────────────────

interface SettingsPanelProps {
  userId: string
  userName: string
  backendUrl: string
  onSignOut: () => void
  onTeamJoined: (teamId: string, teamName: string) => void
}

function SettingsPanel({ userId, userName, backendUrl, onSignOut, onTeamJoined }: SettingsPanelProps) {
  const [profile, setProfile] = useState<{ name: string; email: string; team_id?: string; team_name?: string } | null>(null)
  const [teamMembers, setTeamMembers] = useState<{ user_id: string; name: string; open_tasks: number }[]>([])
  const [inviteCode, setInviteCode] = useState('')
  const [copied, setCopied] = useState(false)
  const [view, setView] = useState<'idle' | 'create' | 'join'>('idle')
  const [inputVal, setInputVal] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!backendUrl || !userId) return
    fetch(`${backendUrl}/api/auth/me?user_id=${userId}`)
      .then(r => r.json())
      .then(data => {
        setProfile(data)
        if (data.team_id) loadTeam(data.team_id)
      })
      .catch(() => {})
  }, [backendUrl, userId]) // eslint-disable-line

  async function loadTeam(teamId: string) {
    try {
      const [overviewRes, inviteRes] = await Promise.all([
        fetch(`${backendUrl}/api/team/overview?team_id=${teamId}`),
        fetch(`${backendUrl}/api/team/generate-invite?team_id=${teamId}`),
      ])
      const overview = await overviewRes.json()
      const invite = await inviteRes.json()
      setTeamMembers(overview.members || [])
      setInviteCode(invite.invite_code || '')
    } catch {}
  }

  async function createTeam() {
    if (!inputVal.trim()) return
    setBusy(true); setError('')
    try {
      const res = await fetch(`${backendUrl}/api/team/create`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: inputVal.trim(), user_id: userId }),
      })
      const data = await res.json()
      setProfile(p => p ? { ...p, team_id: data.team_id, team_name: data.team_name } : p)
      setInviteCode(data.invite_code)
      onTeamJoined(data.team_id, data.team_name)
      await loadTeam(data.team_id)
      setView('idle'); setInputVal('')
    } catch { setError('Failed to create team') }
    finally { setBusy(false) }
  }

  async function joinTeam() {
    if (!inputVal.trim()) return
    setBusy(true); setError('')
    try {
      const res = await fetch(`${backendUrl}/api/team/join`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ invite_code: inputVal.trim().toUpperCase(), user_id: userId }),
      })
      if (!res.ok) { setError('Invalid invite code'); setBusy(false); return }
      const data = await res.json()
      setProfile(p => p ? { ...p, team_id: data.team_id, team_name: data.team_name } : p)
      onTeamJoined(data.team_id, data.team_name)
      await loadTeam(data.team_id)
      setView('idle'); setInputVal('')
    } catch { setError('Failed to join team') }
    finally { setBusy(false) }
  }

  function copyInvite() {
    navigator.clipboard.writeText(inviteCode)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const initials = (profile?.name || userName || '?').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()

  const sectionStyle: React.CSSProperties = {
    padding: '14px 16px',
    borderBottom: '1px solid rgba(90,83,225,0.07)',
  }
  const labelStyle: React.CSSProperties = {
    fontSize: 10, fontWeight: 700, color: '#9B97CC',
    letterSpacing: '0.08em', textTransform: 'uppercase',
    marginBottom: 10, fontFamily: 'IBM Plex Mono, monospace',
  }

  return (
    <div style={{ paddingBottom: 16 }}>

      {/* Profile */}
      <div style={sectionStyle}>
        <div style={labelStyle}>Profile</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 44, height: 44, borderRadius: 14,
            background: 'linear-gradient(135deg, #4A42D8, #6B63E8)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 16, fontWeight: 700, color: 'white', flexShrink: 0,
          }}>
            {initials}
          </div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#1a1730' }}>
              {profile?.name || userName}
            </div>
            <div style={{ fontSize: 12, color: '#9B97CC', marginTop: 2 }}>
              {profile?.email || 'Loading...'}
            </div>
          </div>
        </div>
      </div>

      {/* Team */}
      <div style={sectionStyle}>
        <div style={labelStyle}>Team</div>

        {profile?.team_id ? (
          <>
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              marginBottom: 10,
            }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#1a1730' }}>
                  {profile.team_name}
                </div>
                <div style={{ fontSize: 11, color: '#9B97CC', marginTop: 2 }}>
                  {teamMembers.length} member{teamMembers.length !== 1 ? 's' : ''}
                </div>
              </div>
            </div>

            {/* Invite code */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8,
              background: 'rgba(90,83,225,0.05)', borderRadius: 10,
              padding: '8px 12px', marginBottom: 12,
            }}>
              <span style={{ fontSize: 11, color: '#9B97CC', flex: 1 }}>Invite code</span>
              <span style={{
                fontFamily: 'IBM Plex Mono, monospace', fontSize: 13,
                fontWeight: 700, color: '#5A53E1', letterSpacing: '0.1em',
              }}>
                {inviteCode || '——'}
              </span>
              <button onClick={copyInvite} style={{
                padding: '3px 9px', borderRadius: 7, border: 'none',
                background: copied ? '#2ED573' : '#5A53E1',
                color: 'white', fontSize: 10, fontWeight: 600, cursor: 'pointer',
                transition: 'background 0.2s',
              }}>
                {copied ? 'Copied!' : 'Copy'}
              </button>
            </div>

            {/* Members */}
            {teamMembers.map(m => (
              <div key={m.user_id} style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '6px 0', borderBottom: '1px solid rgba(90,83,225,0.05)',
              }}>
                <div style={{
                  width: 28, height: 28, borderRadius: 9,
                  background: 'linear-gradient(135deg, #A29BFE, #6B63E8)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 10, fontWeight: 700, color: 'white', flexShrink: 0,
                }}>
                  {m.name.split(' ').map((w: string) => w[0]).join('').slice(0, 2).toUpperCase()}
                </div>
                <span style={{ fontSize: 12, color: '#1a1730', flex: 1 }}>{m.name}</span>
                <span style={{ fontSize: 11, color: '#9B97CC' }}>
                  {m.open_tasks} task{m.open_tasks !== 1 ? 's' : ''}
                </span>
              </div>
            ))}
          </>
        ) : (
          <>
            {view === 'idle' && (
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={() => setView('create')} style={{
                  flex: 1, padding: '8px 0', borderRadius: 10, border: 'none',
                  background: 'linear-gradient(135deg, #5A53E1, #7B75F0)',
                  color: 'white', fontSize: 12, fontWeight: 600, cursor: 'pointer',
                }}>
                  Create team
                </button>
                <button onClick={() => setView('join')} style={{
                  flex: 1, padding: '8px 0', borderRadius: 10,
                  border: '1.5px solid rgba(90,83,225,0.2)', background: 'none',
                  color: '#5A53E1', fontSize: 12, fontWeight: 600, cursor: 'pointer',
                }}>
                  Join with code
                </button>
              </div>
            )}
            {(view === 'create' || view === 'join') && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <input
                  autoFocus
                  value={inputVal}
                  onChange={e => { setInputVal(e.target.value); setError('') }}
                  onKeyDown={e => e.key === 'Enter' && (view === 'create' ? createTeam() : joinTeam())}
                  placeholder={view === 'create' ? 'Team name...' : 'Invite code (e.g. AB12CD34)'}
                  style={{
                    padding: '9px 12px', borderRadius: 10, fontSize: 13,
                    border: `1.5px solid ${error ? '#FF4757' : 'rgba(90,83,225,0.2)'}`,
                    outline: 'none', background: 'white', color: '#1a1730',
                    fontFamily: 'inherit',
                  }}
                />
                {error && <div style={{ fontSize: 11, color: '#FF4757' }}>{error}</div>}
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    onClick={view === 'create' ? createTeam : joinTeam}
                    disabled={busy}
                    style={{
                      flex: 1, padding: '8px 0', borderRadius: 10, border: 'none',
                      background: 'linear-gradient(135deg, #5A53E1, #7B75F0)',
                      color: 'white', fontSize: 12, fontWeight: 600,
                      cursor: busy ? 'default' : 'pointer', opacity: busy ? 0.7 : 1,
                    }}
                  >
                    {busy ? '...' : view === 'create' ? 'Create' : 'Join'}
                  </button>
                  <button onClick={() => { setView('idle'); setInputVal(''); setError('') }} style={{
                    padding: '8px 14px', borderRadius: 10,
                    border: '1.5px solid rgba(90,83,225,0.15)', background: 'none',
                    color: '#9B97CC', fontSize: 12, cursor: 'pointer',
                  }}>
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Sign out */}
      <div style={{ padding: '14px 16px' }}>
        <button
          onClick={onSignOut}
          style={{
            width: '100%', padding: '9px 0', borderRadius: 10,
            border: '1.5px solid rgba(255,71,87,0.25)', background: 'rgba(255,71,87,0.04)',
            color: '#FF4757', fontSize: 12, fontWeight: 600, cursor: 'pointer',
            transition: 'all 0.15s',
          }}
          onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,71,87,0.09)' }}
          onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,71,87,0.04)' }}
        >
          Sign out
        </button>
      </div>
    </div>
  )
}

function SectionLabel({ children, color, noMargin }: { children: React.ReactNode; color: string; noMargin?: boolean }) {
  return (
    <div style={{
      fontSize: 10, fontWeight: 700, color, letterSpacing: '0.08em',
      textTransform: 'uppercase', marginBottom: noMargin ? 0 : 6,
      fontFamily: 'IBM Plex Mono, monospace',
    }}>
      {children}
    </div>
  )
}
