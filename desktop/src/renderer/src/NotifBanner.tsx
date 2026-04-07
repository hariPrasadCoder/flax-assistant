import { useEffect, useRef, useState } from 'react'
import { authFetch } from './lib/api'

function renderMarkdown(text: string) {
  const lines = text.split('\n')
  const elements: React.ReactNode[] = []
  let i = 0

  function renderInline(line: string): React.ReactNode[] {
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
    if (line.trim() === '') {
      elements.push(<div key={`sp-${i}`} style={{ height: 4 }} />)
      i++; continue
    }
    if (/^(\s*[-•*]|\s*\d+\.) /.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^(\s*[-•*]|\s*\d+\.) /.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-•*\d.]+\s*/, ''))
        i++
      }
      elements.push(
        <ul key={`ul-${i}`} style={{ margin: '4px 0', paddingLeft: 14, listStyle: 'none' }}>
          {items.map((item, j) => (
            <li key={j} style={{ display: 'flex', gap: 6, marginBottom: 2 }}>
              <span style={{ color: '#5A53E1', flexShrink: 0 }}>•</span>
              <span>{renderInline(item)}</span>
            </li>
          ))}
        </ul>
      )
      continue
    }
    elements.push(
      <p key={`p-${i}`} style={{ margin: 0, marginBottom: i < lines.length - 1 ? 3 : 0 }}>
        {renderInline(line)}
      </p>
    )
    i++
  }
  return elements
}

interface NotifData {
  nudgeId: string
  message: string
  taskTitle?: string
  taskId?: string
  actions: string[]
  backendUrl: string
}

const FlowerIcon = () => (
  <svg width="16" height="16" viewBox="0 0 100 100" fill="none">
    <g fill="none" stroke="white" strokeWidth="3">
      {[0, 72, 144, 216, 288].map((r, i) => (
        <ellipse key={i} cx="50" cy="28" rx="10" ry="16" transform={`rotate(${r}, 50, 50)`} />
      ))}
    </g>
    <circle cx="50" cy="50" r="8" fill="white" />
  </svg>
)

export default function NotifBanner() {
  const [data, setData] = useState<NotifData | null>(null)
  const [visible, setVisible] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const [responding, setResponding] = useState(false)
  const cardRef = useRef<HTMLDivElement>(null)

  // Auto-dismiss after 30 seconds if no interaction
  useEffect(() => {
    if (!visible) return
    const t = setTimeout(() => dismiss(), 30000)
    return () => clearTimeout(t)
  }, [visible]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const unsub = (window as any).flaxie.onNotifData((d: NotifData) => {
      setData(d)
      requestAnimationFrame(() => requestAnimationFrame(() => {
        setVisible(true)
        // Measure card height after render and resize window to fit
        requestAnimationFrame(() => {
          if (cardRef.current) {
            const h = cardRef.current.getBoundingClientRect().height
            ;(window as any).flaxie.resizeNotif(Math.ceil(h) + 20)
          }
        })
      }))
    })

    // Fallback pull
    ;(window as any).flaxie.getNotifData().then((d: NotifData | null) => {
      if (d && !data) {
        setData(d)
        requestAnimationFrame(() => requestAnimationFrame(() => setVisible(true)))
      }
    })

    return () => unsub()
  }, [])

  function dismiss() {
    if (dismissed) return
    setDismissed(true)
    setVisible(false)
    setTimeout(() => (window as any).flaxie.closeNotif(), 380)
  }

  async function handleAction(action: string) {
    if (!data || responding) return
    setResponding(true)

    const isSnooze = /snooze|remind me|later|\b1h\b|\b2h\b|\b30m\b/i.test(action)

    // Store context before opening chat so ChatApp can pick it up on focus
    if (!isSnooze) {
      localStorage.setItem('flaxie_nudge_context', JSON.stringify({
        action,
        nudgeMessage: data.message,
        taskTitle: data.taskTitle || null,
        taskId: data.taskId || null,
      }))
    }

    // Fire-and-forget — backend handles side effects (mark done, ping owner, etc.)
    authFetch(`${data.backendUrl}/api/nudges/${data.nudgeId}/respond`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ response: action }),
    }).catch(() => {})

    if (!isSnooze) {
      ;(window as any).flaxie.openChat()
    }
    dismiss()
  }

  const font = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif'

  return (
    <>
      <style>{`
        * { margin: 0; padding: 0; box-sizing: border-box; -webkit-font-smoothing: antialiased; }
        html, body, #root { width: 100%; height: 100%; background: transparent; overflow: hidden; }
        button:focus { outline: none; }
        button:hover { opacity: 0.85; }
      `}</style>

      <div style={{
        width: '100%', height: '100%',
        display: 'flex', alignItems: 'flex-start', justifyContent: 'flex-end',
        background: 'transparent',
        padding: '10px 10px 0 10px',
        fontFamily: font,
      }}>
        <div ref={cardRef} style={{
          width: '100%',
          background: 'rgba(255, 255, 255, 0.97)',
          borderRadius: '14px',
          border: '1px solid rgba(0,0,0,0.09)',
          boxShadow: '0 4px 32px rgba(0,0,0,0.18), 0 1px 4px rgba(0,0,0,0.08)',
          overflow: 'hidden',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          transform: visible ? 'translateX(0) scale(1)' : 'translateX(100%) scale(0.95)',
          opacity: visible ? 1 : 0,
          transition: 'transform 0.35s cubic-bezier(0.22,1,0.36,1), opacity 0.25s ease',
        }}>
          {/* Top row: app label + close */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: '7px',
            padding: '11px 14px 8px',
          }}>
            {/* Flaxie pill */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: '5px',
              background: 'linear-gradient(135deg, #4A42D8, #6B63E8)',
              borderRadius: '20px',
              padding: '3px 9px 3px 6px',
            }}>
              <FlowerIcon />
              <span style={{
                fontSize: '11px', fontWeight: '600', color: 'white',
                letterSpacing: '0.01em',
              }}>Flaxie</span>
            </div>

            <span style={{ fontSize: '11px', color: '#8A8A8E', marginLeft: '2px' }}>
              now
            </span>

            {/* Spacer */}
            <div style={{ flex: 1 }} />

            {/* Close */}
            <button onClick={dismiss} style={{
              width: '20px', height: '20px', borderRadius: '50%',
              background: 'rgba(0,0,0,0.06)', border: 'none',
              color: '#8A8A8E', fontSize: '13px', lineHeight: 1,
              cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
              transition: 'background 0.15s',
            }}>
              ×
            </button>
          </div>

          {/* Message */}
          <div style={{ padding: '0 14px 12px' }}>
            <div style={{
              fontSize: '13.5px', color: '#1C1C1E', lineHeight: '1.5',
              fontWeight: '400',
            }}>
              {data?.message ? renderMarkdown(data.message) : null}
            </div>
            {data?.taskTitle && (
              <p style={{
                fontSize: '11.5px', color: '#5A53E1', fontWeight: '500',
                marginTop: '4px',
              }}>
                {data.taskTitle}
              </p>
            )}
          </div>

          {/* Divider */}
          <div style={{ height: '1px', background: 'rgba(0,0,0,0.06)', margin: '0 14px' }} />

          {/* Actions */}
          <div style={{
            display: 'flex',
            borderTop: 'none',
          }}>
            {(data?.actions || ['Got it', "Let's talk"]).map((action, i) => {
              const isPrimary = i === 0
              return (
                <button
                  key={i}
                  onClick={() => handleAction(action)}
                  disabled={responding}
                  style={{
                    flex: 1,
                    padding: '10px 8px',
                    border: 'none',
                    borderRight: i < (data?.actions?.length ?? 1) - 1 ? '1px solid rgba(0,0,0,0.06)' : 'none',
                    background: 'transparent',
                    color: isPrimary ? '#4A42D8' : '#3C3C43',
                    fontSize: '13px',
                    fontWeight: isPrimary ? '600' : '400',
                    cursor: responding ? 'default' : 'pointer',
                    fontFamily: font,
                    letterSpacing: '-0.01em',
                    transition: 'background 0.12s',
                  }}
                  onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(0,0,0,0.04)' }}
                  onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = 'transparent' }}
                >
                  {responding && isPrimary ? '...' : action}
                </button>
              )
            })}
          </div>
        </div>
      </div>
    </>
  )
}
