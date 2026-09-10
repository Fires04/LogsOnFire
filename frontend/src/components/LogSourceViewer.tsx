import { useEffect, useMemo, useState } from 'react'
import { Button, Group, Stack, Text, TextInput } from '@mantine/core'
import { IconArrowLeft, IconSearch } from '@tabler/icons-react'
import { api, ApiError } from '../lib/api'
import LogPanel from './LogPanel'
import type { LogSource, ResolveResponse } from '../types/models'

interface Props {
  logSourceId: string
  /** Overrides the fetched log source's label in the panel header, if given. */
  title?: string
  /** Skip the resolve step entirely and go straight to this exact path —
   * used when the caller already knows exactly which file it wants (e.g.
   * picked from AgentDetailPage's flat "Log files" list, which already ran
   * resolve() for every source up front). Works for any mode, including
   * journal/docker, since resolve() already returns their one
   * correctly-prefixed (journal://, docker://) path — this is just that
   * same value handed back in early instead of re-resolved. */
  initialResolvedPath?: string
}

/**
 * Resolves a log source (handling exact_path / glob / regex / journal —
 * including the "pattern matches multiple files, pick one" case) and then
 * renders a live LogPanel for it. Shared by the inline viewer (opened in a
 * Drawer on AgentDetailPage) and the standalone /view/log/:id route ("open
 * in new window"), so the two never drift apart.
 */
export default function LogSourceViewer({ logSourceId, title, initialResolvedPath }: Props) {
  const [logSource, setLogSource] = useState<LogSource | null>(null)
  // The full multi-match list, once resolved — kept around (unlike the old
  // `candidates` state) even after a pick, so "back to matches" doesn't
  // need to re-resolve from scratch.
  const [matchList, setMatchList] = useState<string[] | null>(null)
  const [showingList, setShowingList] = useState(false)
  const [candidateFilter, setCandidateFilter] = useState('')
  const [resolvedPath, setResolvedPath] = useState<string | undefined>(undefined)
  const [warning, setWarning] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setMatchList(null)
    setShowingList(false)
    setCandidateFilter('')
    setResolvedPath(undefined)
    setWarning(null)

    async function load() {
      try {
        const ls = await api.get<LogSource>(`/api/log-sources/${logSourceId}`)
        if (cancelled) return
        setLogSource(ls)

        if (initialResolvedPath) {
          setResolvedPath(initialResolvedPath)
          return
        }

        if (ls.mode === 'exact_path') {
          setResolvedPath(ls.path_or_pattern)
          return
        }

        const result = await api.post<ResolveResponse>(`/api/agents/${ls.agent_id}/log-sources/${ls.id}/resolve`)
        if (cancelled) return
        if (result.warning) setWarning(result.warning)
        if (result.error) {
          setError(result.error)
        } else if (result.files.length === 0) {
          setError('Pattern does not match any file yet.')
        } else if (result.files.length === 1) {
          setResolvedPath(result.files[0].path)
        } else {
          setMatchList(result.files.map((f) => f.path))
          setShowingList(true)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load log source')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [logSourceId, initialResolvedPath])

  const filteredMatches = useMemo(() => {
    if (!matchList) return null
    const needle = candidateFilter.trim().toLowerCase()
    return needle ? matchList.filter((p) => p.toLowerCase().includes(needle)) : matchList
  }, [matchList, candidateFilter])

  if (loading) return <Text c="dimmed">Loading…</Text>
  if (error) return <Text c="red">{error}</Text>
  if (!logSource) return <Text c="red">Log source not found.</Text>

  if (showingList && matchList) {
    return (
      <Stack gap="xs">
        <Text c="dimmed" size="sm">
          The pattern matches multiple files — pick one to watch:
        </Text>
        {matchList.length > 8 && (
          <TextInput
            placeholder="Filter…"
            leftSection={<IconSearch size={14} />}
            value={candidateFilter}
            onChange={(e) => setCandidateFilter(e.currentTarget.value)}
          />
        )}
        {filteredMatches && filteredMatches.length === 0 && (
          <Text c="dimmed" size="sm">
            No matches for "{candidateFilter}".
          </Text>
        )}
        {filteredMatches?.map((path) => (
          <Button
            key={path}
            variant="default"
            justify="flex-start"
            onClick={() => {
              setShowingList(false)
              setResolvedPath(path)
            }}
          >
            {path}
          </Button>
        ))}
      </Stack>
    )
  }

  return (
    <Stack gap="xs" style={{ flex: 1, minHeight: 0 }}>
      {matchList && (
        <Group>
          <Button
            variant="subtle"
            size="xs"
            leftSection={<IconArrowLeft size={14} />}
            onClick={() => {
              setShowingList(true)
              setResolvedPath(undefined)
            }}
          >
            Back to matches
          </Button>
        </Group>
      )}
      {warning && (
        <Text c="yellow" size="sm">
          ⚠ {warning}
        </Text>
      )}
      <LogPanel logSourceId={logSourceId} resolvedPath={resolvedPath} title={title ?? logSource.label} />
    </Stack>
  )
}
