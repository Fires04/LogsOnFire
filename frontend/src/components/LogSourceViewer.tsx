import { useEffect, useState } from 'react'
import { Button, Stack, Text } from '@mantine/core'
import { api, ApiError } from '../lib/api'
import LogPanel from './LogPanel'
import type { LogSource, ResolveResponse } from '../types/models'

interface Props {
  logSourceId: string
  /** Overrides the fetched log source's label in the panel header, if given. */
  title?: string
}

/**
 * Resolves a log source (handling exact_path / glob / regex / journal —
 * including the "pattern matches multiple files, pick one" case) and then
 * renders a live LogPanel for it. Shared by the inline viewer (opened in a
 * Drawer on AgentDetailPage) and the standalone /view/log/:id route ("open
 * in new window"), so the two never drift apart.
 */
export default function LogSourceViewer({ logSourceId, title }: Props) {
  const [logSource, setLogSource] = useState<LogSource | null>(null)
  const [candidates, setCandidates] = useState<string[] | null>(null)
  const [resolvedPath, setResolvedPath] = useState<string | undefined>(undefined)
  const [warning, setWarning] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setCandidates(null)
    setResolvedPath(undefined)
    setWarning(null)

    async function load() {
      try {
        const ls = await api.get<LogSource>(`/api/log-sources/${logSourceId}`)
        if (cancelled) return
        setLogSource(ls)

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
          setCandidates(result.files.map((f) => f.path))
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
  }, [logSourceId])

  if (loading) return <Text c="dimmed">Loading…</Text>
  if (error) return <Text c="red">{error}</Text>
  if (!logSource) return <Text c="red">Log source not found.</Text>

  if (candidates) {
    return (
      <Stack gap="xs">
        <Text c="dimmed" size="sm">
          The pattern matches multiple files — pick one to watch:
        </Text>
        {candidates.map((path) => (
          <Button key={path} variant="default" justify="flex-start" onClick={() => setResolvedPath(path)}>
            {path}
          </Button>
        ))}
      </Stack>
    )
  }

  return (
    <Stack gap="xs" style={{ flex: 1, minHeight: 0 }}>
      {warning && (
        <Text c="yellow" size="sm">
          ⚠ {warning}
        </Text>
      )}
      <LogPanel logSourceId={logSourceId} resolvedPath={resolvedPath} title={title ?? logSource.label} />
    </Stack>
  )
}
