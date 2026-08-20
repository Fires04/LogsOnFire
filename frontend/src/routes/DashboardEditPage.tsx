import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Alert, Button, Group, Paper, Select, Stack, Text, TextInput, Title } from '@mantine/core'
import { IconArrowLeft } from '@tabler/icons-react'
import type { Layout } from 'react-grid-layout'
import { api, ApiError } from '../lib/api'
import DashboardGrid, { type GridPanel } from '../components/DashboardGrid'
import { qualifiedLabel } from '../lib/labels'
import type { Agent, Dashboard, DashboardPanelCreate, LogSource, ResolveResponse } from '../types/models'

const DEFAULT_W = 6
const DEFAULT_H = 6

export default function DashboardEditPage() {
  const { dashboardId } = useParams<{ dashboardId: string }>()
  const navigate = useNavigate()

  const [name, setName] = useState('')
  const [panels, setPanels] = useState<GridPanel[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Every agent's log sources, loaded once, so the picker can search/group
  // across all of them at once instead of a two-step agent -> log-source
  // drill-down.
  const [entries, setEntries] = useState<{ agent: Agent; logSource: LogSource }[]>([])

  const [selectedLogSourceId, setSelectedLogSourceId] = useState<string | null>(null)
  const [candidates, setCandidates] = useState<string[] | null>(null)
  const [resolveWarning, setResolveWarning] = useState<string | null>(null)
  const [resolving, setResolving] = useState(false)

  const load = useCallback(async () => {
    if (!dashboardId) return
    const [dashboard, agents] = await Promise.all([
      api.get<Dashboard>(`/api/dashboards/${dashboardId}`),
      api.get<Agent[]>('/api/agents'),
    ])

    const allEntries: { agent: Agent; logSource: LogSource }[] = []
    await Promise.all(
      agents.map(async (agent) => {
        const sources = await api.get<LogSource[]>(`/api/agents/${agent.id}/log-sources`)
        for (const logSource of sources) allEntries.push({ agent, logSource })
      }),
    )
    setEntries(allEntries)

    setName(dashboard.name)
    setPanels(
      dashboard.panels.map((p) => {
        const entry = allEntries.find((e) => e.logSource.id === p.log_source_id)
        return {
          id: p.id,
          logSourceId: p.log_source_id,
          resolvedPath: p.resolved_path ?? undefined,
          title: entry ? qualifiedLabel(entry.agent, entry.logSource) : (p.resolved_path ?? p.log_source_id),
          x: p.position_x,
          y: p.position_y,
          w: p.width || DEFAULT_W,
          h: p.height || DEFAULT_H,
        }
      }),
    )
  }, [dashboardId])

  useEffect(() => {
    load().finally(() => setLoading(false))
  }, [load])

  const pickerData = useMemo(() => {
    const byAgent = new Map<string, { agent: Agent; items: { value: string; label: string }[] }>()
    for (const { agent, logSource } of entries) {
      if (!byAgent.has(agent.id)) byAgent.set(agent.id, { agent, items: [] })
      byAgent.get(agent.id)!.items.push({ value: logSource.id, label: logSource.label })
    }
    return [...byAgent.values()]
      .sort((a, b) => a.agent.name.localeCompare(b.agent.name))
      .map(({ agent, items }) => ({ group: agent.name, items }))
  }, [entries])

  function nextY() {
    return panels.reduce((max, p) => Math.max(max, p.y + p.h), 0)
  }

  async function handlePickLogSource(logSourceId: string | null) {
    setSelectedLogSourceId(logSourceId)
    setCandidates(null)
    setResolveWarning(null)
    if (!logSourceId) return
    const entry = entries.find((e) => e.logSource.id === logSourceId)
    if (!entry) return
    const { agent, logSource } = entry

    if (logSource.mode === 'exact_path') {
      addPanel(agent, logSource, undefined)
      return
    }

    setResolving(true)
    try {
      const result = await api.post<ResolveResponse>(`/api/agents/${agent.id}/log-sources/${logSource.id}/resolve`)
      if (result.warning) setResolveWarning(result.warning)
      if (result.files.length === 1) {
        addPanel(agent, logSource, result.files[0].path)
      } else if (result.files.length > 1) {
        setCandidates(result.files.map((f) => f.path))
      }
    } finally {
      setResolving(false)
    }
  }

  function addPanel(agent: Agent, logSource: LogSource, resolvedPath: string | undefined) {
    setPanels((prev) => [
      ...prev,
      {
        id: `draft-${crypto.randomUUID()}`,
        logSourceId: logSource.id,
        resolvedPath,
        title: qualifiedLabel(agent, logSource),
        x: 0,
        y: nextY(),
        w: DEFAULT_W,
        h: DEFAULT_H,
      },
    ])
    setSelectedLogSourceId(null)
    setCandidates(null)
  }

  function removePanel(id: string) {
    setPanels((prev) => prev.filter((p) => p.id !== id))
  }

  function handleLayoutChange(layout: Layout) {
    setPanels((prev) =>
      prev.map((p) => {
        const item = layout.find((l) => l.i === p.id)
        return item ? { ...p, x: item.x, y: item.y, w: item.w, h: item.h } : p
      }),
    )
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      const payload: DashboardPanelCreate[] = panels.map((p, i) => ({
        log_source_id: p.logSourceId,
        resolved_path: p.resolvedPath,
        position_x: p.x,
        position_y: p.y,
        width: p.w,
        height: p.h,
        display_order: i,
      }))
      await api.patch(`/api/dashboards/${dashboardId}`, { name, panels: payload })
      navigate('/dashboards')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Text c="dimmed">Loading…</Text>

  const pendingEntry = entries.find((e) => e.logSource.id === selectedLogSourceId)

  return (
    <Stack gap="md" style={{ height: '100%' }}>
      <div>
        <Link to="/dashboards" style={{ color: 'var(--mantine-color-dimmed)', fontSize: '0.85rem' }}>
          <IconArrowLeft size={12} style={{ verticalAlign: -1 }} /> Dashboards
        </Link>
      </div>

      <Group justify="space-between" wrap="wrap">
        <TextInput
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          size="lg"
          variant="unstyled"
          fw={700}
          style={{ flex: 1, minWidth: 200 }}
        />
        <Button onClick={handleSave} loading={saving}>
          Save dashboard
        </Button>
      </Group>
      {error && <Text c="red">{error}</Text>}

      <Paper withBorder p="md" radius="md">
        <Stack gap="xs">
          <Title order={5}>Add panel</Title>
          <Select
            placeholder="Search log sources across every agent…"
            searchable
            clearable
            data={pickerData}
            value={selectedLogSourceId}
            onChange={handlePickLogSource}
          />
          {resolving && <Text c="dimmed" size="sm">Searching for matches…</Text>}
          {resolveWarning && <Text c="yellow" size="sm">⚠ {resolveWarning}</Text>}
          {candidates && pendingEntry && (
            <Alert color="blue" variant="light" title="Pattern matches multiple files — pick one">
              <Stack gap={4}>
                {candidates.map((path) => (
                  <Button
                    key={path}
                    variant="subtle"
                    size="xs"
                    justify="flex-start"
                    onClick={() => addPanel(pendingEntry.agent, pendingEntry.logSource, path)}
                  >
                    {path}
                  </Button>
                ))}
              </Stack>
            </Alert>
          )}
        </Stack>
      </Paper>

      <Text c="dimmed" size="sm">
        Drag panels to rearrange, drag a corner to resize — saved automatically with "Save dashboard".
      </Text>

      {panels.length === 0 ? (
        <Text c="dimmed">No panels yet — add one above.</Text>
      ) : (
        <DashboardGrid panels={panels} onLayoutChange={handleLayoutChange} onRemove={removePanel} />
      )}
    </Stack>
  )
}
