import { motion } from 'framer-motion'

export interface Task {
  id: string
  title: string
  status: 'open' | 'in_progress' | 'done'
  deadline?: string
  assignee?: string
  assignee_id?: string
  owner_id?: string
  nudge_count: number
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

interface Props {
  task: Task
  onDone?: (id: string) => void
  compact?: boolean
  teamMembers?: { user_id: string; name: string }[]
  currentUserId?: string
  onAssign?: (taskId: string, assigneeId: string) => void
  assigningTaskId?: string | null
  setAssigningTaskId?: (id: string | null) => void
}

export default function TaskChip({ task, onDone, compact, teamMembers, currentUserId, onAssign, assigningTaskId, setAssigningTaskId }: Props) {
  const isDone = task.status === 'done'
  const isInProgress = task.status === 'in_progress'
  const dl = formatDeadline(task.deadline)

  return (
    <div style={{ position: 'relative' }}>
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
          : dl.overdue
            ? 'rgba(255, 71, 87, 0.06)'
            : dl.urgent
              ? 'rgba(255, 159, 67, 0.06)'
              : 'white',
        borderRadius: 12,
        border: `1px solid ${
          isDone ? 'rgba(46,213,115,0.2)' :
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

      {/* Title */}
      <div style={{ flex: 1, minWidth: 0 }}>
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

      {/* Deadline pill */}
      {dl.label && (
        <span style={{
          fontSize: 10, fontWeight: 600, whiteSpace: 'nowrap',
          padding: '2px 7px', borderRadius: 20,
          background: dl.overdue ? 'rgba(255,71,87,0.1)' : dl.urgent ? 'rgba(255,159,67,0.1)' : 'rgba(90,83,225,0.08)',
          color: dl.overdue ? '#FF4757' : dl.urgent ? '#E67E22' : '#5A53E1',
        }}>
          {dl.label}
        </span>
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
    </div>
  )
}
