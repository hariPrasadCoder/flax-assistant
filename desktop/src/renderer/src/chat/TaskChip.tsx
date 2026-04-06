import { motion } from 'framer-motion'
import { useState } from 'react'

export interface Task {
  id: string
  title: string
  status: 'open' | 'in_progress' | 'done'
  deadline?: string
  assignee?: string
  assignee_id?: string
  owner_id?: string
  nudge_count: number
  priority?: number
  is_blocked?: boolean
  blocked_reason?: string
  is_recurring?: boolean
  recurrence_days?: number
}

function formatDeadline(deadline?: string): { label: string; urgent: boolean; overdue: boolean } {
  if (!deadline) return { label: '', urgent: false, overdue: false }
  try {
    const d = new Date(deadline)
    const now = new Date()
    const diffMs = d.getTime() - now.getTime()
    const diffH = diffMs / (1000 * 60 * 60)
    const diffD = Math.floor(diffH / 24)

    if (diffH < 0) return { label: `Overdue ${Math.abs(diffD) < 1 ? `${Math.abs(Math.floor(diffH))}h` : `${Math.abs(diffD)}d`}`, urgent: true, overdue: true }
    if (diffH < 2) return { label: `${Math.floor(diffH * 60)}min left`, urgent: true, overdue: false }
    if (diffH < 24) return { label: `Due in ${Math.floor(diffH)}h`, urgent: true, overdue: false }
    if (diffD === 1) return { label: 'Due tomorrow', urgent: false, overdue: false }
    return { label: `Due in ${diffD}d`, urgent: false, overdue: false }
  } catch {
    return { label: '', urgent: false, overdue: false }
  }
}

const PRIORITY_CONFIG: Record<number, { dot: string; label: string | null }> = {
  5: { dot: '#FF4757', label: 'Critical' },
  4: { dot: '#E67E22', label: null },
  3: { dot: '', label: null },
  2: { dot: '#9B97CC', label: null },
  1: { dot: '', label: null },
}

interface Props {
  task: Task
  onDone?: (id: string) => void
  compact?: boolean
  teamMembers?: { user_id: string; name: string }[]
  currentUserId?: string
  onAssign?: (taskId: string, assigneeId: string) => void
  assigningTaskId?: string | null
  setAssigningTaskId?: (id: string | null) => void
  onUpdate?: (id: string, patch: object) => void
  backendUrl?: string
}

export default function TaskChip({
  task, onDone, compact, teamMembers, currentUserId,
  onAssign, assigningTaskId, setAssigningTaskId, onUpdate, backendUrl,
}: Props) {
  const isDone = task.status === 'done'
  const isInProgress = task.status === 'in_progress'
  const dl = formatDeadline(task.deadline)
  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState(task.title)
  const [hovered, setHovered] = useState(false)
  const [showDatePicker, setShowDatePicker] = useState(false)

  const priority = task.priority ?? 3
  const priorityCfg = PRIORITY_CONFIG[priority] || PRIORITY_CONFIG[3]

  async function saveEdit() {
    const trimmed = editValue.trim()
    if (!trimmed || trimmed === task.title) return
    if (onUpdate) onUpdate(task.id, { title: trimmed })
    else if (backendUrl) {
      await fetch(`${backendUrl}/api/tasks/${task.id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: trimmed }),
      }).catch(() => {})
    }
  }

  async function toggleBlocked() {
    const newVal = !task.is_blocked
    if (onUpdate) onUpdate(task.id, { is_blocked: newVal })
    else if (backendUrl) {
      await fetch(`${backendUrl}/api/tasks/${task.id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_blocked: newVal }),
      }).catch(() => {})
    }
  }

  async function saveDeadline(dateStr: string) {
    setShowDatePicker(false)
    if (!dateStr) return
    // Convert local date string to ISO
    const iso = new Date(dateStr + 'T00:00:00').toISOString()
    if (onUpdate) onUpdate(task.id, { deadline: iso })
    else if (backendUrl) {
      await fetch(`${backendUrl}/api/tasks/${task.id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ deadline: iso }),
      }).catch(() => {})
    }
  }

  return (
    <div
      style={{ position: 'relative' }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <motion.div
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: compact ? '7px 10px' : '10px 12px',
          background: isDone
            ? 'rgba(46, 213, 115, 0.06)'
            : task.is_blocked
              ? 'rgba(255,71,87,0.05)'
              : dl.overdue
                ? 'rgba(255, 71, 87, 0.06)'
                : dl.urgent
                  ? 'rgba(255, 159, 67, 0.06)'
                  : 'white',
          borderRadius: 12,
          border: `1px solid ${
            isDone ? 'rgba(46,213,115,0.2)' :
            task.is_blocked ? 'rgba(255,71,87,0.25)' :
            dl.overdue ? 'rgba(255,71,87,0.2)' :
            dl.urgent ? 'rgba(255,159,67,0.2)' :
            'rgba(90, 83, 225, 0.1)'
          }`,
          marginBottom: 6,
        }}
      >
        {/* Checkbox / status */}
        {!isDone && onDone ? (
          <button
            onClick={() => onDone(task.id)}
            title="Mark done"
            style={{
              width: 18, height: 18, borderRadius: 5,
              border: `1.5px solid ${dl.overdue ? '#FF4757' : dl.urgent ? '#FF9F43' : '#C3BFF7'}`,
              background: 'white', cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0, transition: 'all 0.15s',
            }}
          />
        ) : (
          <div style={{
            width: 18, height: 18, borderRadius: 5, flexShrink: 0,
            background: isDone ? '#2ED573' : isInProgress ? '#FF9F43' : 'rgba(90,83,225,0.15)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            {isDone && <span style={{ fontSize: 10, color: 'white' }}>✓</span>}
            {isInProgress && <span style={{ fontSize: 8, color: 'white' }}>▶</span>}
          </div>
        )}

        {/* Title + meta */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            {/* Priority dot */}
            {priorityCfg.dot && (
              <div style={{
                width: 6, height: 6, borderRadius: '50%',
                background: priorityCfg.dot, flexShrink: 0,
              }} />
            )}

            {/* Recurring icon */}
            {task.is_recurring && (
              <span style={{ fontSize: 11, color: '#9B97CC', flexShrink: 0 }}>↻</span>
            )}

            {/* Title — editable */}
            {editing ? (
              <input
                autoFocus
                value={editValue}
                onChange={e => setEditValue(e.target.value)}
                onBlur={() => { saveEdit(); setEditing(false) }}
                onKeyDown={e => {
                  if (e.key === 'Enter') { saveEdit(); setEditing(false) }
                  if (e.key === 'Escape') { setEditValue(task.title); setEditing(false) }
                }}
                style={{
                  fontSize: 13, border: 'none',
                  outline: '1.5px solid rgba(90,83,225,0.3)',
                  borderRadius: 6, padding: '2px 6px',
                  background: 'white', width: '100%', fontFamily: 'inherit',
                  color: '#1a1730',
                }}
              />
            ) : (
              <div style={{
                fontSize: 13,
                fontWeight: 500,
                color: isDone ? '#9B97CC' : '#1a1730',
                textDecoration: isDone ? 'line-through' : 'none',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}>
                {task.title}
              </div>
            )}

            {/* Priority label (critical only) */}
            {priorityCfg.label && (
              <span style={{
                fontSize: 9, fontWeight: 700, color: '#FF4757',
                background: 'rgba(255,71,87,0.1)', borderRadius: 4,
                padding: '1px 5px', flexShrink: 0, letterSpacing: '0.04em',
              }}>
                {priorityCfg.label}
              </span>
            )}
          </div>

          {/* Blocked reason subtitle */}
          {task.is_blocked && task.blocked_reason && (
            <div style={{ fontSize: 11, color: '#9B97CC', marginTop: 2 }}>
              {task.blocked_reason}
            </div>
          )}

          {!compact && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 1, flexWrap: 'wrap' }}>
              {task.assignee && (
                <span style={{ fontSize: 10, color: '#9B97CC' }}>@{task.assignee}</span>
              )}
              {task.assignee_id && currentUserId && task.assignee_id !== currentUserId && task.owner_id === currentUserId && (
                <span style={{
                  fontSize: 10, fontWeight: 600, color: '#5A53E1',
                  background: 'rgba(90,83,225,0.08)', borderRadius: 6, padding: '1px 5px',
                }}>
                  → {task.assignee || task.assignee_id}
                </span>
              )}
              {task.owner_id && currentUserId && task.owner_id !== currentUserId && task.assignee_id === currentUserId && (
                <span style={{ fontSize: 10, color: '#9B97CC' }}>
                  from {teamMembers?.find(m => m.user_id === task.owner_id)?.name || task.owner_id}
                </span>
              )}
            </div>
          )}

          {/* Assign dropdown */}
          {assigningTaskId === task.id && teamMembers && teamMembers.length > 0 && setAssigningTaskId && onAssign && (
            <div style={{
              position: 'absolute', zIndex: 100,
              background: 'white', borderRadius: 10,
              border: '1.5px solid rgba(90,83,225,0.15)',
              boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
              marginTop: 4, minWidth: 140, overflow: 'hidden',
            }}>
              {teamMembers.map(m => (
                <button
                  key={m.user_id}
                  onClick={() => { onAssign(task.id, m.user_id); setAssigningTaskId(null) }}
                  style={{
                    display: 'block', width: '100%', padding: '7px 12px',
                    border: 'none', background: 'none', textAlign: 'left',
                    fontSize: 12, color: '#1a1730', cursor: 'pointer',
                    fontFamily: 'inherit',
                  }}
                  onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(90,83,225,0.06)' }}
                  onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = 'none' }}
                >
                  {m.name}
                </button>
              ))}
              <button
                onClick={() => setAssigningTaskId(null)}
                style={{
                  display: 'block', width: '100%', padding: '5px 12px',
                  border: 'none', borderTop: '1px solid rgba(90,83,225,0.08)',
                  background: 'none', textAlign: 'left',
                  fontSize: 11, color: '#9B97CC', cursor: 'pointer',
                  fontFamily: 'inherit',
                }}
              >
                Cancel
              </button>
            </div>
          )}
        </div>

        {/* Blocked badge */}
        {task.is_blocked && (
          <span style={{
            fontSize: 10, fontWeight: 600, color: '#FF4757',
            background: 'rgba(255,71,87,0.1)', borderRadius: 6,
            padding: '2px 6px', whiteSpace: 'nowrap', flexShrink: 0,
          }}>
            Blocked
          </span>
        )}

        {/* Deadline pill */}
        {dl.label && (
          <span style={{
            fontSize: 10, fontWeight: 600, whiteSpace: 'nowrap',
            padding: '2px 7px', borderRadius: 20,
            background: dl.overdue ? 'rgba(255,71,87,0.1)' : dl.urgent ? 'rgba(255,159,67,0.1)' : 'rgba(90,83,225,0.08)',
            color: dl.overdue ? '#FF4757' : dl.urgent ? '#E67E22' : '#5A53E1',
            cursor: 'pointer', flexShrink: 0,
          }}
            onClick={() => setShowDatePicker(v => !v)}
            title="Change deadline"
          >
            {dl.label}
          </span>
        )}

        {/* Hover actions — only rendered when hovered, no reserved space */}
        {hovered && !isDone && !editing && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 2, flexShrink: 0 }}>
            {/* Edit title */}
            <button
              onClick={() => { setEditing(true); setEditValue(task.title) }}
              title="Edit title"
              style={{
                border: 'none', background: 'none', cursor: 'pointer',
                color: '#C3BFF7', padding: '3px', borderRadius: 5, display: 'flex',
                transition: 'color 0.12s, background 0.12s',
              }}
              onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.color = '#9B97CC'; (e.currentTarget as HTMLButtonElement).style.background = 'rgba(90,83,225,0.07)' }}
              onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.color = '#C3BFF7'; (e.currentTarget as HTMLButtonElement).style.background = 'none' }}
            >
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                <path d="M11.5 2.5a1.5 1.5 0 0 1 2.12 2.12L5 13.25l-2.75.5.5-2.75L11.5 2.5z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>

            {/* Set / change deadline */}
            <button
              onClick={() => setShowDatePicker(v => !v)}
              title={dl.label ? 'Change deadline' : 'Set deadline'}
              style={{
                border: 'none', background: 'none', cursor: 'pointer',
                color: '#C3BFF7', padding: '3px', borderRadius: 5, display: 'flex',
                transition: 'color 0.12s, background 0.12s',
              }}
              onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.color = '#9B97CC'; (e.currentTarget as HTMLButtonElement).style.background = 'rgba(90,83,225,0.07)' }}
              onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.color = '#C3BFF7'; (e.currentTarget as HTMLButtonElement).style.background = 'none' }}
            >
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                <rect x="1.5" y="3" width="13" height="11.5" rx="2" stroke="currentColor" strokeWidth="1.5"/>
                <path d="M5 1.5v3M11 1.5v3M1.5 7h13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
            </button>

            {/* Block / unblock */}
            <button
              onClick={toggleBlocked}
              title={task.is_blocked ? 'Unblock' : 'Mark blocked'}
              style={{
                border: 'none', background: 'none', cursor: 'pointer',
                color: task.is_blocked ? '#FF4757' : '#C3BFF7',
                padding: '3px', borderRadius: 5, display: 'flex',
                transition: 'color 0.12s, background 0.12s',
              }}
              onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.color = '#FF4757'; (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,71,87,0.07)' }}
              onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.color = task.is_blocked ? '#FF4757' : '#C3BFF7'; (e.currentTarget as HTMLButtonElement).style.background = 'none' }}
            >
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeWidth="1.5"/>
                <path d="M3.5 3.5l9 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
            </button>
          </div>
        )}

        {/* Assign button (only for unassigned own tasks when team members exist) */}
        {!isDone && teamMembers && teamMembers.length > 0 && currentUserId &&
         task.owner_id === currentUserId && task.assignee_id === currentUserId &&
         setAssigningTaskId && (
          <button
            onClick={() => setAssigningTaskId(assigningTaskId === task.id ? null : task.id)}
            style={{
              padding: '2px 7px', borderRadius: 20, border: 'none',
              background: 'rgba(90,83,225,0.08)', color: '#5A53E1',
              fontSize: 10, fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap',
              fontFamily: 'inherit',
            }}
          >
            Assign
          </button>
        )}
      </motion.div>

      {/* Inline date picker */}
      {showDatePicker && (
        <div style={{
          position: 'absolute', right: 0, zIndex: 200,
          background: 'white', borderRadius: 10,
          border: '1.5px solid rgba(90,83,225,0.2)',
          boxShadow: '0 4px 16px rgba(0,0,0,0.1)',
          padding: '8px 10px', marginTop: 2,
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <input
            type="date"
            autoFocus
            defaultValue={task.deadline ? task.deadline.slice(0, 10) : ''}
            onChange={e => saveDeadline(e.target.value)}
            onBlur={() => setShowDatePicker(false)}
            onKeyDown={e => { if (e.key === 'Escape') setShowDatePicker(false) }}
            style={{
              border: 'none', outline: 'none', fontSize: 12,
              color: '#1a1730', fontFamily: 'inherit', background: 'none',
            }}
          />
          <button
            onClick={() => setShowDatePicker(false)}
            style={{ border: 'none', background: 'none', color: '#9B97CC', cursor: 'pointer', fontSize: 12 }}
          >
            ✕
          </button>
        </div>
      )}
    </div>
  )
}
