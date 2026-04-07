/**
 * parseTaskDate
 *
 * Extracts a deadline from natural-language task text and returns the
 * cleaned title + ISO deadline string.
 *
 * Examples:
 *   "Submit report by tomorrow"      → { title: "Submit report",        deadline: <tomorrow> }
 *   "Call client next Friday"         → { title: "Call client",          deadline: <next Friday> }
 *   "Deploy by April 3"               → { title: "Deploy",               deadline: <April 3> }
 *   "Fix bug in 2 days"               → { title: "Fix bug",              deadline: <+2 days> }
 *   "Finish designs by end of week"   → { title: "Finish designs",       deadline: <this Friday> }
 *   "Stand up at 9am"                 → { title: "Stand up",             deadline: <today 9am> }
 */

const DAYS = ['sunday','monday','tuesday','wednesday','thursday','friday','saturday']
const DAY_SHORT = ['sun','mon','tue','wed','thu','fri','sat']
const MONTHS = [
  'january','february','march','april','may','june',
  'july','august','september','october','november','december',
]
const MONTH_SHORT = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']

/** Return the next occurrence of a weekday (0=Sun…6=Sat). If today is that day, returns next week. */
function nextWeekday(target: number, from: Date, allowToday = false): Date {
  const d = new Date(from)
  d.setHours(23, 59, 0, 0)
  const diff = (target - d.getDay() + 7) % 7
  d.setDate(d.getDate() + (diff === 0 ? (allowToday ? 0 : 7) : diff))
  return d
}

function startOfDay(d: Date, hour = 23, min = 59): Date {
  const r = new Date(d)
  r.setHours(hour, min, 0, 0)
  return r
}

function parseTime(timeStr: string, base: Date): Date | null {
  const m = timeStr.match(/(\d{1,2})(?::(\d{2}))?\s*(am|pm)?/i)
  if (!m) return null
  let h = parseInt(m[1])
  const min = m[2] ? parseInt(m[2]) : 0
  const ampm = m[3]?.toLowerCase()
  if (ampm === 'pm' && h < 12) h += 12
  if (ampm === 'am' && h === 12) h = 0
  const d = new Date(base)
  d.setHours(h, min, 0, 0)
  return d
}

export interface ParseResult {
  title: string
  deadline: string | null  // ISO string or null
  deadlineLabel: string | null  // human-readable, e.g. "Tomorrow", "Friday"
}

export function parseTaskDate(input: string): ParseResult {
  const now = new Date()
  const text = input.trim()

  // Preposition prefixes that can precede a date expression
  const PRE = '(?:by|due(?:\\s+by)?|on|at|for|before|this|–|-|,|\\()?\\s*'

  type Candidate = { match: string; date: Date; label: string }
  const candidates: Candidate[] = []

  function tryMatch(pattern: RegExp, resolver: (m: RegExpMatchArray) => { date: Date; label: string } | null) {
    const m = text.match(pattern)
    if (!m) return
    const result = resolver(m)
    if (!result) return
    // Ignore dates in the past (more than 1 hour ago)
    if (result.date.getTime() < now.getTime() - 3600_000) return
    candidates.push({ match: m[0], date: result.date, label: result.label })
  }

  // ── 1. Tomorrow ──────────────────────────────────────────────────────────────
  tryMatch(new RegExp(`${PRE}\\btomorrow\\b(?:\\s+(?:morning|afternoon|evening|night))?`, 'i'), (m) => {
    const d = startOfDay(now)
    d.setDate(d.getDate() + 1)
    return { date: d, label: 'Tomorrow' }
  })

  // ── 2. Today / tonight / EOD / COB ──────────────────────────────────────────
  tryMatch(new RegExp(`${PRE}\\b(?:today|tonight|eod|cob|end\\s+of\\s+(?:the\\s+)?day)\\b`, 'i'), () => {
    return { date: startOfDay(now, 17, 0), label: 'Today' }
  })

  // ── 3. End of week ───────────────────────────────────────────────────────────
  tryMatch(new RegExp(`${PRE}\\bend\\s+of\\s+(?:the\\s+)?week\\b`, 'i'), () => {
    return { date: nextWeekday(5, now), label: 'End of week' }  // Friday
  })

  // ── 4. End of month ──────────────────────────────────────────────────────────
  tryMatch(new RegExp(`${PRE}\\bend\\s+of\\s+(?:the\\s+)?month\\b`, 'i'), () => {
    const d = new Date(now.getFullYear(), now.getMonth() + 1, 0, 23, 59)
    return { date: d, label: 'End of month' }
  })

  // ── 5. Next <weekday> ────────────────────────────────────────────────────────
  tryMatch(
    new RegExp(`${PRE}\\bnext\\s+(${[...DAYS, ...DAY_SHORT].join('|')})\\b`, 'i'),
    (m) => {
      const dayStr = m[1].toLowerCase()
      const idx = DAYS.indexOf(dayStr) !== -1 ? DAYS.indexOf(dayStr) : DAY_SHORT.indexOf(dayStr)
      const d = nextWeekday(idx, now, false)
      // "next" always means the one after the coming one if today matches
      if (d.getDay() === now.getDay()) d.setDate(d.getDate() + 7)
      return { date: d, label: `Next ${DAYS[idx].charAt(0).toUpperCase() + DAYS[idx].slice(1)}` }
    }
  )

  // ── 6. <weekday> / this <weekday> (without "next") ───────────────────────────
  tryMatch(
    new RegExp(`(?:^|\\s)(?:this\\s+)?(${[...DAYS, ...DAY_SHORT].join('|')})\\b`, 'i'),
    (m) => {
      const dayStr = m[1].toLowerCase()
      const idx = DAYS.indexOf(dayStr) !== -1 ? DAYS.indexOf(dayStr) : DAY_SHORT.indexOf(dayStr)
      const d = nextWeekday(idx, now, false)
      return { date: d, label: DAYS[idx].charAt(0).toUpperCase() + DAYS[idx].slice(1) }
    }
  )

  // ── 7. Month + day  (e.g. "April 3", "Apr 3rd", "3 April") ──────────────────
  const monthNames = [...MONTHS, ...MONTH_SHORT].join('|')
  tryMatch(
    new RegExp(`${PRE}\\b(?:(${monthNames})\\s+(\\d{1,2})(?:st|nd|rd|th)?|(\\d{1,2})(?:st|nd|rd|th)?\\s+(${monthNames}))\\b`, 'i'),
    (m) => {
      const [monthStr, dayStr] = m[1]
        ? [m[1], m[2]]
        : [m[4], m[3]]
      const mIdx = MONTHS.indexOf(monthStr.toLowerCase()) !== -1
        ? MONTHS.indexOf(monthStr.toLowerCase())
        : MONTH_SHORT.indexOf(monthStr.toLowerCase())
      const day = parseInt(dayStr)
      let year = now.getFullYear()
      const candidate = new Date(year, mIdx, day, 23, 59)
      if (candidate < now) year++  // bump to next year if already passed
      const d = new Date(year, mIdx, day, 23, 59)
      const label = `${MONTHS[mIdx].charAt(0).toUpperCase() + MONTHS[mIdx].slice(1)} ${day}`
      return { date: d, label }
    }
  )

  // ── 8. In N hours / days / weeks ─────────────────────────────────────────────
  tryMatch(/\bin\s+(\d+)\s+(hours?|days?|weeks?)\b/i, (m) => {
    const n = parseInt(m[1])
    const unit = m[2].toLowerCase()
    const d = new Date(now)
    if (unit.startsWith('hour')) d.setHours(d.getHours() + n)
    else if (unit.startsWith('day')) d.setDate(d.getDate() + n)
    else d.setDate(d.getDate() + n * 7)
    return { date: d, label: `In ${n} ${unit}` }
  })

  // ── 9. Time only: "at 3pm", "at 9:30am" — defaults to today, or tomorrow if past ──
  tryMatch(/\bat\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b/i, (m) => {
    let d = parseTime(m[1], now)
    if (!d) return null
    if (d < now) d.setDate(d.getDate() + 1)  // bump to tomorrow if time has passed
    const label = m[1].trim()
    return { date: d, label }
  })

  if (candidates.length === 0) {
    return { title: text, deadline: null, deadlineLabel: null }
  }

  // Pick the earliest match (most imminent deadline)
  candidates.sort((a, b) => a.date.getTime() - b.date.getTime())
  const { match, date, label } = candidates[0]

  // Strip the matched expression from the title
  let title = text
    .replace(match, ' ')           // remove the matched date fragment
    .replace(/\s*[-–,]\s*$/, '')   // trailing punctuation
    .replace(/\s*[-–,]\s*(?=\s|$)/, ' ')
    .replace(/\(\s*\)/g, '')       // empty parens leftover
    .replace(/\s{2,}/g, ' ')       // collapse spaces
    .trim()

  // Edge-case: if stripping leaves nothing, keep original minus the date
  if (!title) title = text.replace(match, '').trim()

  return { title, deadline: date.toISOString(), deadlineLabel: label }
}
