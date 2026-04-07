import { motion } from 'framer-motion'
import { format } from 'date-fns'

/** Render markdown-lite: bold, bullet lists, line breaks. No dependencies. */
function renderMarkdown(text: string, isUser: boolean) {
  const lines = text.split('\n')
  const elements: React.ReactNode[] = []
  let i = 0

  function renderInline(line: string): React.ReactNode[] {
    // **bold** or *bold*
    const parts = line.split(/(\*\*.*?\*\*|\*.*?\*)/g)
    return parts.map((part, idx) => {
      if (part.startsWith('**') && part.endsWith('**'))
        return <strong key={idx}>{part.slice(2, -2)}</strong>
      if (part.startsWith('*') && part.endsWith('*'))
        return <em key={idx}>{part.slice(1, -1)}</em>
      return part
    })
  }

  while (i < lines.length) {
    const line = lines[i]

    // Blank line → spacer
    if (line.trim() === '') {
      elements.push(<div key={`sp-${i}`} style={{ height: 6 }} />)
      i++; continue
    }

    // Bullet list block: collect consecutive bullet lines
    if (/^(\s*[-•*]|\s*\d+\.) /.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^(\s*[-•*]|\s*\d+\.) /.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-•*\d.]+\s*/, ''))
        i++
      }
      elements.push(
        <ul key={`ul-${i}`} style={{
          margin: '4px 0', paddingLeft: 16, listStyle: 'none',
        }}>
          {items.map((item, j) => (
            <li key={j} style={{ display: 'flex', gap: 7, marginBottom: 3 }}>
              <span style={{ color: isUser ? 'rgba(255,255,255,0.6)' : '#5A53E1', flexShrink: 0, marginTop: 1 }}>•</span>
              <span>{renderInline(item)}</span>
            </li>
          ))}
        </ul>
      )
      continue
    }

    // Normal line
    elements.push(
      <p key={`p-${i}`} style={{ margin: 0, marginBottom: i < lines.length - 1 ? 4 : 0 }}>
        {renderInline(line)}
      </p>
    )
    i++
  }

  return elements
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  task_refs?: { id: string; title: string }[]
}

function FlaxieAvatar() {
  return (
    <div style={{
      width: 26, height: 26, borderRadius: '50%', flexShrink: 0,
      background: 'linear-gradient(135deg, #4A42D8, #6B63E8)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <svg width="14" height="14" viewBox="0 0 100 100" fill="none">
        <g fill="none" stroke="white" strokeWidth="3">
          {[0, 72, 144, 216, 288].map((r, i) => (
            <ellipse key={i} cx="50" cy="28" rx="10" ry="16" transform={`rotate(${r}, 50, 50)`} />
          ))}
        </g>
        <circle cx="50" cy="50" r="8" fill="white" />
      </svg>
    </div>
  )
}

interface Props {
  message: Message
  isLatest: boolean
}

export default function MessageBubble({ message, isLatest }: Props) {
  const isUser = message.role === 'user'

  return (
    <motion.div
      initial={isLatest ? { opacity: 0, y: 6 } : { opacity: 1, y: 0 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 420, damping: 32 }}
      style={{
        display: 'flex',
        flexDirection: isUser ? 'row-reverse' : 'row',
        alignItems: 'flex-end',
        gap: 7,
        marginBottom: 14,
      }}
    >
      {!isUser && <FlaxieAvatar />}

      <div style={{ maxWidth: '78%' }}>
        <div style={{
          fontSize: 9,
          fontWeight: 700,
          letterSpacing: '0.07em',
          textTransform: 'uppercase',
          color: isUser ? '#9B97CC' : '#5A53E1',
          marginBottom: 4,
          textAlign: isUser ? 'right' : 'left',
          fontFamily: 'IBM Plex Mono, monospace',
        }}>
          {isUser ? 'You' : 'Flaxie'} · {format(new Date(message.timestamp), 'h:mm a')}
        </div>

        <div style={{
          padding: '10px 14px',
          borderRadius: isUser ? '16px 4px 16px 16px' : '4px 16px 16px 16px',
          fontSize: 13.5,
          lineHeight: 1.6,
          ...(isUser ? {
            background: 'linear-gradient(135deg, #5A53E1, #7B75F0)',
            color: 'white',
            boxShadow: '0 2px 12px rgba(90,83,225,0.3)',
          } : {
            background: 'white',
            color: '#1a1730',
            border: '1px solid rgba(90, 83, 225, 0.1)',
            boxShadow: '0 1px 6px rgba(0,0,0,0.06)',
          }),
        }}>
          {renderMarkdown(message.content, isUser)}
        </div>

        {message.task_refs && message.task_refs.length > 0 && (
          <div style={{ display: 'flex', gap: 4, marginTop: 6, flexWrap: 'wrap' }}>
            {message.task_refs.map((t) => (
              <span key={t.id} style={{
                fontSize: 11, padding: '3px 9px',
                background: 'rgba(90, 83, 225, 0.09)',
                color: '#5A53E1', borderRadius: 20, fontWeight: 500,
                border: '1px solid rgba(90,83,225,0.15)',
              }}>
                📎 {t.title}
              </span>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  )
}
