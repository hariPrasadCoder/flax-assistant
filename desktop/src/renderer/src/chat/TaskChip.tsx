import { motion } from 'framer-motion'

export interface Task {
  id: string
  title: string
  status: 'open' | 'in_progress' | 'done'
  deadline?: string
  assignee?: string
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
}

export default function TaskChip({ task, onDone, compact }: Props) {
  const isDone = task.status === 'done'
  const isInProgress = task.status === 'in_progress'
  const dl = formatDeadline(task.deadline)

  return (
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
        {task.assignee && !compact && (
          <div style={{ fontSize: 10, color: '#9B97CC', marginTop: 1 }}>@{task.assignee}</div>
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
    </motion.div>
  )
}
