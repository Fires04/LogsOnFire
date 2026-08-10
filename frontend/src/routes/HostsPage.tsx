import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import HostForm from '../components/HostForm'
import Modal from '../components/Modal'
import type { Host, HostCreateInput, HostUpdateInput, TestConnectionResult } from '../types/models'

export default function HostsPage() {
  const [hosts, setHosts] = useState<Host[]>([])
  const [loading, setLoading] = useState(true)
  const [testResults, setTestResults] = useState<Record<string, TestConnectionResult>>({})
  const [testing, setTesting] = useState<Record<string, boolean>>({})
  const [search, setSearch] = useState('')
  const [editingHost, setEditingHost] = useState<Host | null>(null)

  const refresh = useCallback(async () => {
    setHosts(await api.get<Host[]>('/api/hosts'))
  }, [])

  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [refresh])

  const filteredHosts = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return hosts
    return hosts.filter((h) =>
      [h.name, h.hostname, h.ssh_username].some((v) => v?.toLowerCase().includes(q)),
    )
  }, [hosts, search])

  async function handleCreate(input: HostCreateInput | HostUpdateInput) {
    await api.post('/api/hosts', input as HostCreateInput)
    await refresh()
  }

  async function handleUpdate(input: HostCreateInput | HostUpdateInput) {
    if (!editingHost) return
    await api.patch(`/api/hosts/${editingHost.id}`, input as HostUpdateInput)
    setEditingHost(null)
    await refresh()
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this host and all of its log sources?')) return
    await api.delete(`/api/hosts/${id}`)
    await refresh()
  }

  async function handleTest(id: string) {
    setTesting((t) => ({ ...t, [id]: true }))
    try {
      const result = await api.post<TestConnectionResult>(`/api/hosts/${id}/test-connection`)
      setTestResults((r) => ({ ...r, [id]: result }))
    } catch (err) {
      setTestResults((r) => ({
        ...r,
        [id]: { success: false, message: err instanceof ApiError ? err.message : 'Error' },
      }))
    } finally {
      setTesting((t) => ({ ...t, [id]: false }))
    }
  }

  async function handleResetTrust(id: string) {
    if (!confirm('Forget the stored SSH host key and trust it again on the next connection?')) return
    const result = await api.post<TestConnectionResult>(`/api/hosts/${id}/reset-trust`)
    setTestResults((r) => ({ ...r, [id]: result }))
  }

  return (
    <div className="page">
      <header className="page-header">
        <h1>Hosts</h1>
      </header>

      <div className="layout-two-col">
        <section>
          <div className="list-toolbar">
            <h2>Hosts</h2>
            {hosts.length > 0 && (
              <input
                className="search-box"
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search hosts…"
                aria-label="Search hosts"
              />
            )}
          </div>
          {loading ? (
            <p>Loading…</p>
          ) : hosts.length === 0 ? (
            <p className="muted">No hosts yet. Add one on the right.</p>
          ) : filteredHosts.length === 0 ? (
            <p className="muted">No hosts match "{search}".</p>
          ) : (
            <ul className="host-list compact">
              {filteredHosts.map((h) => (
                <li key={h.id} className="host-row">
                  <div className="host-row-info">
                    <strong>{h.name}</strong>
                    <span className="muted">
                      {h.connection_type === 'local'
                        ? 'local'
                        : `${h.ssh_username}@${h.hostname}:${h.port} (${h.auth_type === 'password' ? 'password' : 'key'})`}
                    </span>
                    {testResults[h.id] && (
                      <span className={testResults[h.id].success ? 'ok' : 'error'}>
                        {testResults[h.id].message}
                      </span>
                    )}
                  </div>
                  <div className="host-row-actions">
                    <Link className="btn-link" to={`/hosts/${h.id}`}>
                      Log sources
                    </Link>
                    <button className="secondary" onClick={() => setEditingHost(h)}>
                      Edit
                    </button>
                    <button onClick={() => handleTest(h.id)} disabled={testing[h.id]}>
                      {testing[h.id] ? 'Testing…' : 'Test'}
                    </button>
                    {h.connection_type === 'ssh' && (
                      <button onClick={() => handleResetTrust(h.id)} className="secondary">
                        Reset trust
                      </button>
                    )}
                    <button onClick={() => handleDelete(h.id)} className="danger">
                      Delete
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <HostForm onSubmit={handleCreate} />
      </div>

      {editingHost && (
        <Modal onClose={() => setEditingHost(null)}>
          <HostForm editingHost={editingHost} onSubmit={handleUpdate} onCancel={() => setEditingHost(null)} />
        </Modal>
      )}
    </div>
  )
}
