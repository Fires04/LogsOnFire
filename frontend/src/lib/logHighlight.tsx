import type { ReactNode } from 'react'

/** Lightweight, purely client-side log-line syntax highlighting — no
 * per-line-format config, just pattern recognition for the handful of things
 * that show up in almost every log format (timestamps, severity words,
 * bracketed tags/PIDs, IPs, quoted strings) so a raw stream reads more like
 * a structured one at a glance. Deliberately conservative: it never touches
 * bare numbers or arbitrary words, since that gets noisy fast. */

const LEVEL_ERROR = new Set(['EMERG', 'EMERGENCY', 'ALERT', 'CRIT', 'CRITICAL', 'FATAL', 'ERROR', 'ERR'])
const LEVEL_WARN = new Set(['WARN', 'WARNING'])
const LEVEL_INFO = new Set(['NOTICE', 'INFO'])
const LEVEL_DEBUG = new Set(['DEBUG', 'TRACE'])

const TOKEN_RE =
  /(?<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)|(?<level>\b(?:EMERG(?:ENCY)?|ALERT|CRIT(?:ICAL)?|FATAL|ERROR|ERR|WARN(?:ING)?|NOTICE|INFO|DEBUG|TRACE)\b)|(?<ip>\b(?:\d{1,3}\.){3}\d{1,3}\b)|(?<bracket>\[[^\]\n]{1,80}\])|(?<quoted>"[^"\n]*"|'[^'\n]*')/g

function levelClassName(word: string): string {
  const upper = word.toUpperCase()
  if (LEVEL_ERROR.has(upper)) return 'log-tok-level-error'
  if (LEVEL_WARN.has(upper)) return 'log-tok-level-warn'
  if (LEVEL_INFO.has(upper)) return 'log-tok-level-info'
  if (LEVEL_DEBUG.has(upper)) return 'log-tok-level-debug'
  return ''
}

let keySeq = 0

// Skip highlighting past this many characters into a single line — a
// pathologically long line (e.g. a JSON blob) shouldn't make every render
// re-scan tens of thousands of characters for cosmetic coloring.
const SCAN_LIMIT = 4000

export function highlightLogLine(text: string): ReactNode[] {
  if (!text) return [text]

  const nodes: ReactNode[] = []
  let lastIndex = 0
  TOKEN_RE.lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = TOKEN_RE.exec(text)) !== null) {
    if (match.index >= SCAN_LIMIT) break
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index))
    }
    const groups = match.groups ?? {}
    let className = ''
    if (groups.timestamp) className = 'log-tok-timestamp'
    else if (groups.level) className = levelClassName(groups.level)
    else if (groups.ip) className = 'log-tok-ip'
    else if (groups.bracket) className = 'log-tok-bracket'
    else if (groups.quoted) className = 'log-tok-quoted'

    if (className) {
      nodes.push(
        <span className={className} key={++keySeq}>
          {match[0]}
        </span>,
      )
    } else {
      nodes.push(match[0])
    }
    lastIndex = match.index + match[0].length
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex))
  }
  return nodes
}
