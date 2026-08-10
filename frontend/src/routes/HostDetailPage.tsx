import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import LogSourceForm from '../components/LogSourceForm'
import LogSourceViewer from '../components/LogSourceViewer'
import Modal from '../components/Modal'
import type { Host, LogSource, LogSourceCreateInput, ResolveResponse } from '../types/models'

const MODE_LABELS: Record<LogSource['mode'], string> = {
  exact_path: 'exact path',
  glob: 'glob',
  regex: 'regex',
  journal: 'journal',
}

export default function HostDetailPage() {
  const { hostId } = useParams<{ hostId: string }>()
  const [host, setHost] = useState<Host | null>(null)
  const [sources, setSources] = useState<LogSource[]>([])
  const [loading, setLoading] = useState(true)
  const [matches, setMatches] = useState<Record<string, ResolveResponse>>({})
  const [resolving, setResolving] = useState<Record<string, boolean>>({})
  const [viewingId, setViewingId] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!hostId) return
    const [h, ls] = await Promise.all([
      api.get<Host>(`/api/hosts/${hostId}`),
      api.get<LogSource[]>(`/api/hosts/${hostId}/log-sources`),
    ])
    setHost(h)
    setSources(ls)
  }, [hostId])

  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [refresh])

  async function handleCreate(input: LogSourceCreateInput) {
    await api.post(`/api/hosts/${hostId}/log-sources`, input)
    await refresh()
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this log source?')) return
    await api.delete(`/api/hosts/${hostId}/log-sources/${id}`)
    await refresh()
  }

  async function handleResolve(id: string) {
    setResolving((r) => ({ ...r, [id]: true }))
    try {
      const result = await api.post<ResolveResponse>(`/api/hosts/${hostId}/log-sources/${id}/resolve`)
      setMatches((m) => ({ ...m, [id]: result }))
    } catch (err) {
      setMatches((m) => ({
        ...m,
        [id]: { files: [], truncated: false, error: err instanceof ApiError ? err.message : 'Error', warning: null },
      }))
    } finally {
      setResolving((r) => ({ ...r, [id]: false }))
    }
  }

  if (loading) return <div className="page">Loading…</div>

  return (
    <div className="page">
      <header className="page-header">
        <p className="muted">
          <Link to="/hosts">← Hosts</Link>
        </p>
        <h1>{host?.name} — log sources</h1>
      </header>

      <div className="layout-two-col">
        <section>
          {sources.length === 0 ? (
            <p className="muted">No log sources yet. Add one on the right.</p>
          ) : (
            <ul className="host-list">
              {sources.map((s) => (
                <li key={s.id} className="card host-card">
                  <div className="host-card-main">
                    <strong>{s.label}</strong>
                    <span className="muted">
                      [{MODE_LABELS[s.mode]}] {s.mode === 'regex' ? `${s.regex_base_dir} :: ` : ''}
                      <code>{s.path_or_pattern}</code>
                    </span>
                  </div>
                  <div className="host-card-actions">
                    <button onClick={() => setViewingId(s.id)}>View live</button>
                    <button onClick={() => handleResolve(s.id)} disabled={resolving[s.id]}>
                      {resolving[s.id] ? 'Searching…' : 'Show matches'}
                    </button>
                    <button onClick={() => handleDelete(s.id)} className="danger">
                      Delete
                    </button>
                  </div>
                  {matches[s.id] && (
                    <div className="preview-box">
                      {matches[s.id].warning && <p className="warning">⚠ {matches[s.id].warning}</p>}
                      {matches[s.id].error ? (
                        <p className="error">{matches[s.id].error}</p>
                      ) : matches[s.id].files.length === 0 ? (
                        <p className="muted">No matches.</p>
                      ) : (
                        <ul className="preview-list">
                          {matches[s.id].files.map((f) => (
                            <li key={f.path}>
                              <code>{f.path}</code>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        {hostId && <LogSourceForm hostId={hostId} onCreate={handleCreate} />}
      </div>

      {viewingId && (
        <Modal onClose={() => setViewingId(null)} big>
          <div className="log-viewer-modal">
            <div className="log-viewer-modal-header">
              <strong>{sources.find((s) => s.id === viewingId)?.label}</strong>
              <div className="log-viewer-modal-actions">
                {/* Extra, not primary — the modal itself is the normal way to view a log now. */}
                <Link to={`/view/log/${viewingId}`} target="_blank" rel="noreferrer" className="muted">
                  Open in new window ↗
                </Link>
                <button className="secondary" onClick={() => setViewingId(null)}>
                  Close ✕
                </button>
              </div>
            </div>
            <LogSourceViewer logSourceId={viewingId} />
          </div>
        </Modal>
      )}
    </div>
  )
}
