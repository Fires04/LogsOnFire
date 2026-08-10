import { memo, useCallback, useEffect, useRef, useState } from 'react'
import { logWsClient, type FilteredLine, type LogEvent } from '../lib/wsClient'
import { highlightLogLine } from '../lib/logHighlight'

interface DisplayLine {
  key: number
  text: string
  isMatch?: boolean
  isSeparator?: boolean
}

interface Props {
  logSourceId: string
  resolvedPath?: string
  title?: string
}

const FILTER_DEBOUNCE_MS = 300
const COLORIZE_STORAGE_KEY = 'logsonfire.colorizeLogs'

const LogLine = memo(function LogLine({ line, colorize }: { line: DisplayLine; colorize: boolean }) {
  const className = line.isSeparator
    ? 'log-line log-line-separator'
    : line.isMatch
      ? 'log-line log-line-match'
      : 'log-line'
  return <div className={className}>{colorize && !line.isSeparator ? highlightLogLine(line.text) : line.text}</div>
})

let keySeq = 0
function toDisplayLines(texts: string[]): DisplayLine[] {
  return texts.map((text) => ({ key: ++keySeq, text }))
}
function toDisplayLinesFiltered(lines: FilteredLine[]): DisplayLine[] {
  return lines.map((l) => ({ key: ++keySeq, text: l.text, isMatch: l.is_match, isSeparator: l.is_separator }))
}

export default function LogPanel({ logSourceId, resolvedPath, title }: Props) {
  const [lines, setLines] = useState<DisplayLine[]>([])
  const [status, setStatus] = useState<'connecting' | 'live' | 'reconnecting' | 'error' | 'closed'>('connecting')
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [filterInput, setFilterInput] = useState('')
  const [filterError, setFilterError] = useState<string | null>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const [colorize, setColorize] = useState(() => localStorage.getItem(COLORIZE_STORAGE_KEY) !== 'off')

  const subIdRef = useRef<string | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const onEvent = useCallback((event: LogEvent) => {
    switch (event.type) {
      case 'backfill':
        setLines(toDisplayLines(event.lines))
        setStatus('live')
        setStatusMessage(null)
        break
      case 'line':
        setLines((prev) => [...prev, ...toDisplayLines([event.text])])
        break
      case 'filtered_snapshot':
        setFilterError(null)
        setLines(toDisplayLinesFiltered(event.lines))
        break
      case 'filter_error':
        setFilterError(event.message)
        break
      case 'error':
        setStatus('error')
        setStatusMessage(event.message)
        break
      case 'closed':
        setStatus('closed')
        setStatusMessage(event.reason)
        break
      case 'reconnecting':
        setStatus('reconnecting')
        setStatusMessage('connection lost, retrying…')
        break
    }
  }, [])

  useEffect(() => {
    setStatus('connecting')
    const subId = logWsClient.subscribe(logSourceId, resolvedPath, onEvent)
    subIdRef.current = subId

    return () => {
      logWsClient.unsubscribe(subId)
      subIdRef.current = null
    }
  }, [logSourceId, resolvedPath, onEvent])

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [lines, autoScroll])

  function handleScroll() {
    const el = scrollRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    setAutoScroll(atBottom)
  }

  function applyFilter(value: string) {
    setFilterInput(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      if (!subIdRef.current) return
      if (value.trim()) {
        logWsClient.setFilter(subIdRef.current, value.trim())
      } else {
        setFilterError(null)
        logWsClient.clearFilter(subIdRef.current)
      }
    }, FILTER_DEBOUNCE_MS)
  }

  function toggleColorize(value: boolean) {
    setColorize(value)
    localStorage.setItem(COLORIZE_STORAGE_KEY, value ? 'on' : 'off')
  }

  return (
    <div className="log-panel">
      <div className="log-panel-header">
        {title && <strong className="log-panel-title">{title}</strong>}
        <input
          className="grep-bar"
          value={filterInput}
          onChange={(e) => applyFilter(e.target.value)}
          placeholder="grep expression, e.g. -i error -C 3"
          spellCheck={false}
        />
        <label className="log-panel-colorize">
          <input type="checkbox" checked={colorize} onChange={(e) => toggleColorize(e.target.checked)} />
          colors
        </label>
        <span className={`status-dot status-${status}`} title={statusMessage ?? status} />
      </div>
      {filterError && <p className="error grep-error">{filterError}</p>}
      {status === 'error' && <p className="error">{statusMessage}</p>}
      {status === 'closed' && <p className="muted">Connection closed ({statusMessage}).</p>}
      {status === 'reconnecting' && <p className="muted">{statusMessage}</p>}
      <div className="log-lines" ref={scrollRef} onScroll={handleScroll}>
        {lines.map((l) => (
          <LogLine key={l.key} line={l} colorize={colorize} />
        ))}
      </div>
    </div>
  )
}
