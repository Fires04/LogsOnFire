import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../lib/api'
import DashboardGrid, { type GridPanel } from '../components/DashboardGrid'
import type { Dashboard, LogSource } from '../types/models'

export default function DashboardViewPage() {
  const { dashboardId } = useParams<{ dashboardId: string }>()
  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [panels, setPanels] = useState<GridPanel[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!dashboardId) return
    let cancelled = false

    async function load() {
      try {
        const d = await api.get<Dashboard>(`/api/dashboards/${dashboardId}`)
        if (cancelled) return
        setDashboard(d)

        const labels = await Promise.all(
          d.panels.map((p) =>
            api.get<LogSource>(`/api/log-sources/${p.log_source_id}`).catch(() => null),
          ),
        )
        if (cancelled) return
        setPanels(
          d.panels.map((p, i) => ({
            id: p.id,
            logSourceId: p.log_source_id,
            resolvedPath: p.resolved_path ?? undefined,
            title: labels[i]?.label ?? p.resolved_path ?? p.log_source_id,
            width: p.width,
          })),
        )
      } catch {
        if (!cancelled) setError('Failed to load dashboard.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [dashboardId])

  if (loading) return <div className="standalone-page">Loading…</div>
  if (error) return <div className="standalone-page error">{error}</div>
  if (!dashboard) return <div className="standalone-page error">Dashboard not found.</div>

  return (
    <div className="standalone-page">
      <h1>{dashboard.name}</h1>
      {panels.length === 0 ? <p className="muted">This dashboard has no panels yet.</p> : <DashboardGrid panels={panels} />}
    </div>
  )
}
