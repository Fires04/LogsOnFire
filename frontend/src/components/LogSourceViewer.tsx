import { useEffect, useState } from 'react'
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
 * renders a live LogPanel for it. Shared by the inline viewer (opened right
 * on HostDetailPage) and the standalone /view/log/:id route ("open in new
 * window"), so the two never drift apart.
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

        const result = await api.post<ResolveResponse>(`/api/hosts/${ls.host_id}/log-sources/${ls.id}/resolve`)
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

  if (loading) return <p className="muted">Loading…</p>
  if (error) return <p className="error">{error}</p>
  if (!logSource) return <p className="error">Log source not found.</p>

  if (candidates) {
    return (
      <div className="log-source-viewer-candidates">
        <p className="muted">The pattern matches multiple files — pick one to watch:</p>
        <ul className="preview-list">
          {candidates.map((path) => (
            <li key={path}>
              <button onClick={() => setResolvedPath(path)}>{path}</button>
            </li>
          ))}
        </ul>
      </div>
    )
  }

  return (
    <div className="log-source-viewer">
      {warning && <p className="warning log-source-viewer-warning">⚠ {warning}</p>}
      <LogPanel logSourceId={logSourceId} resolvedPath={resolvedPath} title={title ?? logSource.label} />
    </div>
  )
}
