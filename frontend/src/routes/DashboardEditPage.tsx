import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import type { Dashboard, DashboardPanelCreate, Host, LogSource, ResolveResponse } from '../types/models'

interface DraftPanel extends DashboardPanelCreate {
  label: string // display-only, not persisted directly (derived from log source + resolved path)
}

export default function DashboardEditPage() {
  const { dashboardId } = useParams<{ dashboardId: string }>()
  const navigate = useNavigate()

  const [name, setName] = useState('')
  const [panels, setPanels] = useState<DraftPanel[]>([])
  const [hosts, setHosts] = useState<Host[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // "add panel" form state
  const [selectedHostId, setSelectedHostId] = useState('')
  const [hostLogSources, setHostLogSources] = useState<LogSource[]>([])
  const [selectedLogSourceId, setSelectedLogSourceId] = useState('')
  const [selectedResolvedPath, setSelectedResolvedPath] = useState<string | undefined>(undefined)
  const [candidates, setCandidates] = useState<string[] | null>(null)
  const [resolveWarning, setResolveWarning] = useState<string | null>(null)
  const [resolving, setResolving] = useState(false)
  const [width, setWidth] = useState(6)

  const load = useCallback(async () => {
    if (!dashboardId) return
    const [dashboard, hostList] = await Promise.all([
      api.get<Dashboard>(`/api/dashboards/${dashboardId}`),
      api.get<Host[]>('/api/hosts'),
    ])
    setName(dashboard.name)
    setPanels(
      dashboard.panels.map((p) => ({
        log_source_id: p.log_source_id,
        resolved_path: p.resolved_path ?? undefined,
        position_x: p.position_x,
        position_y: p.position_y,
        width: p.width,
        height: p.height,
        display_order: p.display_order,
        label: p.resolved_path ?? p.log_source_id,
      })),
    )
    setHosts(hostList)
  }, [dashboardId])

  useEffect(() => {
    load().finally(() => setLoading(false))
  }, [load])

  useEffect(() => {
    setSelectedLogSourceId('')
    setCandidates(null)
    if (!selectedHostId) {
      setHostLogSources([])
      return
    }
    api.get<LogSource[]>(`/api/hosts/${selectedHostId}/log-sources`).then(setHostLogSources)
  }, [selectedHostId])

  async function handlePickLogSource(logSourceId: string) {
    setSelectedLogSourceId(logSourceId)
    setCandidates(null)
    setSelectedResolvedPath(undefined)
    setResolveWarning(null)
    const source = hostLogSources.find((s) => s.id === logSourceId)
    if (!source) return
    if (source.mode === 'exact_path') return // no resolving needed, resolved_path stays undefined

    setResolving(true)
    try {
      const result = await api.post<ResolveResponse>(
        `/api/hosts/${selectedHostId}/log-sources/${logSourceId}/resolve`,
      )
      if (result.warning) setResolveWarning(result.warning)
      if (result.files.length === 1) {
        // Deterministic (journal, or a pattern that happens to match exactly
        // one file) — skip straight to the width/add step, same as exact_path.
        setSelectedResolvedPath(result.files[0].path)
      } else if (result.files.length > 1) {
        setCandidates(result.files.map((f) => f.path))
      }
    } finally {
      setResolving(false)
    }
  }

  function addPanel(resolvedPath?: string) {
    const source = hostLogSources.find((s) => s.id === selectedLogSourceId)
    if (!source) return
    setPanels((prev) => [
      ...prev,
      {
        log_source_id: source.id,
        resolved_path: resolvedPath,
        position_x: 0,
        position_y: prev.length,
        width,
        height: 6,
        display_order: prev.length,
        label: `${source.label}${resolvedPath ? ` — ${resolvedPath}` : ''}`,
      },
    ])
    setSelectedLogSourceId('')
    setSelectedResolvedPath(undefined)
    setCandidates(null)
  }

  function removePanel(index: number) {
    setPanels((prev) => prev.filter((_, i) => i !== index))
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      await api.patch(`/api/dashboards/${dashboardId}`, {
        name,
        panels: panels.map(({ label: _label, ...p }, i) => ({ ...p, display_order: i, position_y: i })),
      })
      navigate('/dashboards')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="page">Loading…</div>

  return (
    <div className="page">
      <header className="page-header">
        <p className="muted">
          <Link to="/dashboards">← Dashboards</Link>
        </p>
        <label>
          Dashboard name
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
      </header>

      <div className="layout-two-col">
        <section>
          <h2>Panels ({panels.length})</h2>
          {panels.length === 0 ? (
            <p className="muted">No panels yet.</p>
          ) : (
            <ul className="host-list">
              {panels.map((p, i) => (
                <li key={i} className="card host-card">
                  <div className="host-card-main">
                    <code>{p.label}</code>
                    <span className="muted">width {p.width}/12</span>
                  </div>
                  <div className="host-card-actions">
                    <button onClick={() => removePanel(i)} className="danger">
                      Remove
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {error && <p className="error">{error}</p>}
          <button onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save dashboard'}
          </button>
        </section>

        <div className="card">
          <h2>Add panel</h2>
          <label>
            Host
            <select value={selectedHostId} onChange={(e) => setSelectedHostId(e.target.value)}>
              <option value="">— select a host —</option>
              {hosts.map((h) => (
                <option key={h.id} value={h.id}>
                  {h.name}
                </option>
              ))}
            </select>
          </label>

          {selectedHostId && (
            <label>
              Log source
              <select value={selectedLogSourceId} onChange={(e) => handlePickLogSource(e.target.value)}>
                <option value="">— select a log source —</option>
                {hostLogSources.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
          )}

          {resolving && <p className="muted">Searching for matches…</p>}
          {!resolving && resolveWarning && <p className="warning">⚠ {resolveWarning}</p>}

          {selectedLogSourceId && !candidates && !resolving && (
            <>
              <label>
                Panel width
                <select value={width} onChange={(e) => setWidth(Number(e.target.value))}>
                  <option value={12}>Full row</option>
                  <option value={6}>Half</option>
                  <option value={4}>Third</option>
                </select>
              </label>
              <button onClick={() => addPanel(selectedResolvedPath)}>Add panel</button>
            </>
          )}

          {candidates && (
            <div className="preview-box">
              <p className="muted">The pattern matches multiple files — pick one for this panel:</p>
              <ul className="preview-list">
                {candidates.map((path) => (
                  <li key={path}>
                    <button onClick={() => addPanel(path)}>{path}</button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
