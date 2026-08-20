import { memo, useCallback, useEffect, useRef, useState } from 'react'
import { ActionIcon, Checkbox, Group, Indicator, Menu, Text, TextInput, Tooltip } from '@mantine/core'
import { IconBookmark, IconDeviceFloppy, IconSearch, IconX } from '@tabler/icons-react'
import { logWsClient, type FilteredLine, type LogEvent } from '../lib/wsClient'
import { highlightLogLine } from '../lib/logHighlight'
import { useSavedFilters } from '../lib/savedFilters'

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

type Status = 'connecting' | 'live' | 'reconnecting' | 'error' | 'closed'

const STATUS_COLOR: Record<Status, string> = {
  connecting: 'yellow',
  reconnecting: 'yellow',
  live: 'teal',
  error: 'red',
  closed: 'gray',
}

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
  const [status, setStatus] = useState<Status>('connecting')
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [filterInput, setFilterInput] = useState('')
  const [filterError, setFilterError] = useState<string | null>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const [colorize, setColorize] = useState(() => localStorage.getItem(COLORIZE_STORAGE_KEY) !== 'off')
  const { filters: savedFilters, save: saveFilter, remove: removeFilter } = useSavedFilters()

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

  function pushFilterToServer(value: string) {
    if (!subIdRef.current) return
    if (value.trim()) {
      logWsClient.setFilter(subIdRef.current, value.trim())
    } else {
      setFilterError(null)
      logWsClient.clearFilter(subIdRef.current)
    }
  }

  function applyFilter(value: string) {
    setFilterInput(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => pushFilterToServer(value), FILTER_DEBOUNCE_MS)
  }

  /** Picking a saved filter (or clearing) should take effect immediately,
   * not wait out the debounce meant for "still typing". */
  function applySavedFilter(expression: string) {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    setFilterInput(expression)
    pushFilterToServer(expression)
  }

  async function handleSaveCurrentFilter() {
    const expression = filterInput.trim()
    if (!expression) return
    const label = window.prompt('Save this filter as:', expression)
    if (!label || !label.trim()) return
    try {
      await saveFilter({ label: label.trim(), expression })
    } catch {
      // best-effort convenience feature — a failed save just means "try again", not worth a modal
    }
  }

  function toggleColorize(value: boolean) {
    setColorize(value)
    localStorage.setItem(COLORIZE_STORAGE_KEY, value ? 'on' : 'off')
  }

  const statusLabel =
    status === 'live' ? 'Live' : status === 'closed' ? `Closed${statusMessage ? ` (${statusMessage})` : ''}`
      : status === 'error' ? `Error${statusMessage ? `: ${statusMessage}` : ''}`
        : status === 'reconnecting' ? 'Reconnecting…' : 'Connecting…'

  return (
    <div className="log-panel">
      <Group gap="xs" px="xs" py={6} wrap="nowrap" style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>
        {title && (
          <Text fw={600} size="sm" c="white" style={{ maxWidth: '30%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flexShrink: 0 }}>
            {title}
          </Text>
        )}
        <TextInput
          size="xs"
          leftSection={<IconSearch size={14} />}
          value={filterInput}
          onChange={(e) => applyFilter(e.currentTarget.value)}
          placeholder="grep expression, e.g. -i error -C 3"
          spellCheck={false}
          style={{ flex: 1, fontFamily: 'var(--mono)' }}
          styles={{ input: { fontFamily: 'var(--mono)' } }}
        />
        <Tooltip label="Save current filter">
          <ActionIcon
            size="sm"
            variant="subtle"
            disabled={!filterInput.trim()}
            onClick={handleSaveCurrentFilter}
          >
            <IconDeviceFloppy size={14} />
          </ActionIcon>
        </Tooltip>
        <Menu withinPortal position="bottom-end" shadow="md">
          <Menu.Target>
            <Tooltip label="Saved filters">
              <ActionIcon size="sm" variant="subtle">
                <IconBookmark size={14} />
              </ActionIcon>
            </Tooltip>
          </Menu.Target>
          <Menu.Dropdown miw={220}>
            {savedFilters.length === 0 ? (
              <Menu.Item disabled>No saved filters yet</Menu.Item>
            ) : (
              savedFilters.map((f) => (
                <Menu.Item key={f.id} component="div" style={{ cursor: 'pointer' }} onClick={() => applySavedFilter(f.expression)}>
                  <Group justify="space-between" wrap="nowrap" gap="xs">
                    <div style={{ minWidth: 0 }}>
                      <Text size="sm" truncate>
                        {f.label}
                      </Text>
                      <Text size="xs" c="dimmed" ff="var(--mono)" truncate>
                        {f.expression}
                      </Text>
                    </div>
                    <ActionIcon
                      size="xs"
                      variant="subtle"
                      color="red"
                      onClick={(e) => {
                        e.stopPropagation()
                        if (confirm(`Delete saved filter "${f.label}"?`)) removeFilter(f.id)
                      }}
                    >
                      <IconX size={12} />
                    </ActionIcon>
                  </Group>
                </Menu.Item>
              ))
            )}
          </Menu.Dropdown>
        </Menu>
        <Checkbox
          size="xs"
          label="colors"
          checked={colorize}
          onChange={(e) => toggleColorize(e.currentTarget.checked)}
          styles={{ label: { color: 'var(--mantine-color-dimmed)', fontSize: '0.78rem' } }}
        />
        <Tooltip label={statusLabel}>
          <Indicator color={STATUS_COLOR[status]} size={10} processing={status === 'connecting' || status === 'reconnecting'} />
        </Tooltip>
      </Group>
      {filterError && (
        <Text size="sm" c="red" px="xs" py={4} bg="rgba(192, 57, 43, 0.1)">
          {filterError}
        </Text>
      )}
      {status === 'error' && (
        <Text size="sm" c="red" px="xs" py={4}>
          {statusMessage}
        </Text>
      )}
      {status === 'closed' && (
        <Text size="sm" c="dimmed" px="xs" py={4}>
          Connection closed ({statusMessage}).
        </Text>
      )}
      {status === 'reconnecting' && (
        <Text size="sm" c="dimmed" px="xs" py={4}>
          {statusMessage}
        </Text>
      )}
      <div className="log-lines" ref={scrollRef} onScroll={handleScroll}>
        {lines.map((l) => (
          <LogLine key={l.key} line={l} colorize={colorize} />
        ))}
      </div>
    </div>
  )
}
