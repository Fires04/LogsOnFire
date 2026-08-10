import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import type { Dashboard } from '../types/models'

export default function DashboardsListPage() {
  const [dashboards, setDashboards] = useState<Dashboard[]>([])
  const [loading, setLoading] = useState(true)
  const [name, setName] = useState('')
  const navigate = useNavigate()

  const refresh = useCallback(async () => {
    setDashboards(await api.get<Dashboard[]>('/api/dashboards'))
  }, [])

  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [refresh])

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    if (!name.trim()) return
    const dashboard = await api.post<Dashboard>('/api/dashboards', { name: name.trim(), panels: [] })
    navigate(`/dashboards/${dashboard.id}/edit`)
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this dashboard?')) return
    await api.delete(`/api/dashboards/${id}`)
    await refresh()
  }

  return (
    <div className="page">
      <header className="page-header">
        <h1>Dashboards</h1>
      </header>

      <div className="layout-two-col">
        <section>
          {loading ? (
            <p>Loading…</p>
          ) : dashboards.length === 0 ? (
            <p className="muted">No dashboards yet. Create one on the right.</p>
          ) : (
            <ul className="host-list">
              {dashboards.map((d) => (
                <li key={d.id} className="card host-card">
                  <div className="host-card-main">
                    <strong>{d.name}</strong>
                    <span className="muted">{d.panels.length} panels</span>
                  </div>
                  <div className="host-card-actions">
                    <Link to={`/dashboards/${d.id}/edit`}>Edit</Link>
                    <Link to={`/view/dashboard/${d.id}`} target="_blank" rel="noreferrer">
                      Open live ↗
                    </Link>
                    <button onClick={() => handleDelete(d.id)} className="danger">
                      Delete
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <form className="card" onSubmit={handleCreate}>
          <h2>New dashboard</h2>
          <label>
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="e.g. Production" />
          </label>
          <button type="submit">Create and edit</button>
        </form>
      </div>
    </div>
  )
}
