import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Text, Title } from '@mantine/core'
import { api } from '../lib/api'
import DashboardGrid, { type GridPanel } from '../components/DashboardGrid'
import { qualifiedLabel } from '../lib/labels'
import type { Agent, Dashboard, LogSource } from '../types/models'

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

        const logSources = await Promise.all(
          d.panels.map((p) => api.get<LogSource>(`/api/log-sources/${p.log_source_id}`).catch(() => null)),
        )
        const agentIds = [...new Set(logSources.filter((ls): ls is LogSource => !!ls).map((ls) => ls.agent_id))]
        const agents = await Promise.all(agentIds.map((id) => api.get<Agent>(`/api/agents/${id}`).catch(() => null)))
        const agentById = new Map(agents.filter((a): a is Agent => !!a).map((a) => [a.id, a]))

        if (cancelled) return
        setPanels(
          d.panels.map((p, i) => {
            const ls = logSources[i]
            const agent = ls ? agentById.get(ls.agent_id) : undefined
            return {
              id: p.id,
              logSourceId: p.log_source_id,
              resolvedPath: p.resolved_path ?? undefined,
              title: ls ? qualifiedLabel(agent, ls) : (p.resolved_path ?? p.log_source_id),
              x: p.position_x,
              y: p.position_y,
              w: p.width || 6,
              h: p.height || 6,
            }
          }),
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
  if (error) return <div className="standalone-page"><Text c="red">{error}</Text></div>
  if (!dashboard) return <div className="standalone-page"><Text c="red">Dashboard not found.</Text></div>

  return (
    <div className="standalone-page">
      <Title order={2} mb="sm">{dashboard.name}</Title>
      {panels.length === 0 ? (
        <Text c="dimmed">This dashboard has no panels yet.</Text>
      ) : (
        <DashboardGrid panels={panels} />
      )}
    </div>
  )
}
