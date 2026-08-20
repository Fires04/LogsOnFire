import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import dayjs from 'dayjs'
import { DataTable } from 'mantine-datatable'
import {
  ActionIcon,
  Alert,
  Badge,
  Card,
  Drawer,
  Group,
  Indicator,
  Stack,
  Text,
  Title,
  Tooltip,
} from '@mantine/core'
import { IconAlertTriangle, IconArrowLeft, IconEye, IconExternalLink, IconListSearch, IconTrash } from '@tabler/icons-react'
import { api, ApiError } from '../lib/api'
import LogSourceForm from '../components/LogSourceForm'
import LogSourceViewer from '../components/LogSourceViewer'
import type { Agent, LogSource, LogSourceCreateInput, ResolveResponse } from '../types/models'

const MODE_LABEL: Record<LogSource['mode'], string> = {
  exact_path: 'exact path',
  glob: 'glob',
  regex: 'regex',
  journal: 'journal',
}
const MODE_COLOR: Record<LogSource['mode'], string> = {
  exact_path: 'blue',
  glob: 'grape',
  regex: 'orange',
  journal: 'teal',
}

export default function AgentDetailPage() {
  const { agentId } = useParams<{ agentId: string }>()
  const [agent, setAgent] = useState<Agent | null>(null)
  const [sources, setSources] = useState<LogSource[]>([])
  const [loading, setLoading] = useState(true)
  const [matches, setMatches] = useState<Record<string, ResolveResponse>>({})
  const [resolving, setResolving] = useState<Record<string, boolean>>({})
  const [expandedIds, setExpandedIds] = useState<string[]>([])
  const [viewingId, setViewingId] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!agentId) return
    const [a, ls] = await Promise.all([
      api.get<Agent>(`/api/agents/${agentId}`),
      api.get<LogSource[]>(`/api/agents/${agentId}/log-sources`),
    ])
    setAgent(a)
    setSources(ls)
  }, [agentId])

  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [refresh])

  async function handleCreate(input: LogSourceCreateInput) {
    await api.post(`/api/agents/${agentId}/log-sources`, input)
    await refresh()
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this log source?')) return
    await api.delete(`/api/agents/${agentId}/log-sources/${id}`)
    await refresh()
  }

  async function handleResolve(id: string) {
    setResolving((r) => ({ ...r, [id]: true }))
    try {
      const result = await api.post<ResolveResponse>(`/api/agents/${agentId}/log-sources/${id}/resolve`)
      setMatches((m) => ({ ...m, [id]: result }))
      setExpandedIds((ids) => (ids.includes(id) ? ids : [...ids, id]))
    } catch (err) {
      setMatches((m) => ({
        ...m,
        [id]: { files: [], truncated: false, error: err instanceof ApiError ? err.message : 'Error', warning: null },
      }))
      setExpandedIds((ids) => (ids.includes(id) ? ids : [...ids, id]))
    } finally {
      setResolving((r) => ({ ...r, [id]: false }))
    }
  }

  if (loading || !agent) return <Text c="dimmed">Loading…</Text>

  return (
    <Stack gap="md">
      <div>
        <Link to="/agents" style={{ color: 'var(--mantine-color-dimmed)', fontSize: '0.85rem' }}>
          <IconArrowLeft size={12} style={{ verticalAlign: -1 }} /> Agents
        </Link>
      </div>

      <Card withBorder radius="md" p="md">
        <Group justify="space-between" wrap="wrap">
          <div>
            <Title order={3}>{agent.name}</Title>
            <Group gap={6} mt={4}>
              <Indicator color={agent.online ? 'teal' : 'gray'} size={9} processing={agent.online} />
              <Text size="sm">{agent.online ? 'Online' : 'Offline'}</Text>
              {agent.last_seen_at && (
                <Tooltip label={new Date(agent.last_seen_at).toLocaleString()}>
                  <Text size="sm" c="dimmed">
                    · last seen {dayjs(agent.last_seen_at).fromNow()}
                    {agent.last_heartbeat_rtt_ms != null ? ` · ${agent.last_heartbeat_rtt_ms} ms RTT` : ''}
                  </Text>
                </Tooltip>
              )}
            </Group>
          </div>
          {agent.agent_version && <Badge variant="light">{agent.agent_version}</Badge>}
        </Group>
      </Card>

      {!agent.online && (
        <Alert icon={<IconAlertTriangle size={16} />} color="yellow" variant="light">
          Agent is offline — browsing files and resolving patterns will fail until it reconnects.
        </Alert>
      )}

      <Title order={4}>Log sources</Title>
      <DataTable
        withTableBorder
        borderRadius="md"
        minHeight={sources.length === 0 ? 120 : undefined}
        records={sources}
        noRecordsText="No log sources yet — add one below."
        columns={[
          { accessor: 'label', title: 'Label', render: (s) => <Text fw={600}>{s.label}</Text> },
          {
            accessor: 'mode',
            title: 'Mode',
            render: (s) => (
              <Badge color={MODE_COLOR[s.mode]} variant="light">
                {MODE_LABEL[s.mode]}
              </Badge>
            ),
          },
          {
            accessor: 'path_or_pattern',
            title: 'Path / pattern',
            render: (s) => (
              <Text component="code" fz="sm">
                {s.mode === 'regex' ? `${s.regex_base_dir} :: ` : ''}
                {s.path_or_pattern}
              </Text>
            ),
          },
          {
            accessor: 'actions',
            title: '',
            textAlign: 'right',
            render: (s) => (
              <Group gap={4} justify="flex-end" wrap="nowrap">
                <Tooltip label="View live">
                  <ActionIcon variant="subtle" onClick={() => setViewingId(s.id)}>
                    <IconEye size={16} />
                  </ActionIcon>
                </Tooltip>
                <Tooltip label="Show matches">
                  <ActionIcon variant="subtle" onClick={() => handleResolve(s.id)} loading={resolving[s.id]}>
                    <IconListSearch size={16} />
                  </ActionIcon>
                </Tooltip>
                <Tooltip label="Delete">
                  <ActionIcon variant="subtle" color="red" onClick={() => handleDelete(s.id)}>
                    <IconTrash size={16} />
                  </ActionIcon>
                </Tooltip>
              </Group>
            ),
          },
        ]}
        rowExpansion={{
          allowMultiple: true,
          trigger: 'never',
          expanded: { recordIds: expandedIds, onRecordIdsChange: setExpandedIds },
          content: ({ record: s }) =>
            matches[s.id] ? (
              <Stack gap={4} p="xs">
                {matches[s.id].warning && (
                  <Text size="sm" c="yellow">
                    ⚠ {matches[s.id].warning}
                  </Text>
                )}
                {matches[s.id].error ? (
                  <Text size="sm" c="red">
                    {matches[s.id].error}
                  </Text>
                ) : matches[s.id].files.length === 0 ? (
                  <Text size="sm" c="dimmed">
                    No matches.
                  </Text>
                ) : (
                  matches[s.id].files.map((f) => (
                    <Text key={f.path} component="code" fz="sm">
                      {f.path}
                    </Text>
                  ))
                )}
              </Stack>
            ) : null,
        }}
      />

      {agentId && <LogSourceForm agentId={agentId} onCreate={handleCreate} />}

      <Drawer opened={viewingId !== null} onClose={() => setViewingId(null)} position="right" size="60%" title={
        <Group gap="sm">
          <Text fw={600}>{sources.find((s) => s.id === viewingId)?.label}</Text>
          {viewingId && (
            <Link to={`/view/log/${viewingId}`} target="_blank" rel="noreferrer" style={{ color: 'var(--mantine-color-dimmed)' }}>
              <IconExternalLink size={14} style={{ verticalAlign: -2 }} /> open in new window
            </Link>
          )}
        </Group>
      }>
        {viewingId && (
          <div style={{ height: 'calc(100vh - 100px)', display: 'flex' }}>
            <LogSourceViewer logSourceId={viewingId} />
          </div>
        )}
      </Drawer>
    </Stack>
  )
}
