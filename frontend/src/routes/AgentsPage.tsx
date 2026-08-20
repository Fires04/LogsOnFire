import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { DataTable, type DataTableSortStatus } from 'mantine-datatable'
import {
  ActionIcon,
  Badge,
  Button,
  CopyButton,
  Group,
  Indicator,
  Menu,
  Stack,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core'
import {
  IconDots,
  IconKey,
  IconPlus,
  IconSearch,
  IconTrash,
} from '@tabler/icons-react'
import { api } from '../lib/api'
import AgentForm from '../components/AgentForm'
import Modal from '../components/Modal'
import type { Agent, AgentCreateInput, AgentCreateResult, AgentUpdateInput } from '../types/models'

dayjs.extend(relativeTime)

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [sortStatus, setSortStatus] = useState<DataTableSortStatus<Agent>>({ columnAccessor: 'name', direction: 'asc' })
  const [creating, setCreating] = useState(false)
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null)
  const [revealedToken, setRevealedToken] = useState<AgentCreateResult | null>(null)

  const refresh = useCallback(async () => {
    setAgents(await api.get<Agent[]>('/api/agents'))
  }, [])

  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [refresh])

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase()
    const filtered = q ? agents.filter((a) => a.name.toLowerCase().includes(q)) : agents
    const sorted = [...filtered].sort((a, b) => {
      const dir = sortStatus.direction === 'asc' ? 1 : -1
      switch (sortStatus.columnAccessor) {
        case 'online':
          return (Number(a.online) - Number(b.online)) * dir
        case 'last_seen_at':
          return ((a.last_seen_at ?? '').localeCompare(b.last_seen_at ?? '')) * dir
        default:
          return a.name.localeCompare(b.name) * dir
      }
    })
    return sorted
  }, [agents, search, sortStatus])

  async function handleCreate(input: AgentCreateInput | AgentUpdateInput) {
    const result = await api.post<AgentCreateResult>('/api/agents', input as AgentCreateInput)
    setCreating(false)
    setRevealedToken(result)
    await refresh()
  }

  async function handleRename(input: AgentCreateInput | AgentUpdateInput) {
    if (!editingAgent) return
    await api.patch(`/api/agents/${editingAgent.id}`, input as AgentUpdateInput)
    setEditingAgent(null)
    await refresh()
  }

  async function handleDelete(agent: Agent) {
    if (!confirm(`Delete agent "${agent.name}" and all of its log sources?`)) return
    await api.delete(`/api/agents/${agent.id}`)
    await refresh()
  }

  async function handleReissue(agent: Agent) {
    if (!confirm(`Reissue "${agent.name}"'s token? The current one stops working immediately.`)) return
    const result = await api.post<AgentCreateResult>(`/api/agents/${agent.id}/reissue-token`)
    setRevealedToken(result)
    await refresh()
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Agents</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
          New agent
        </Button>
      </Group>

      <TextInput
        placeholder="Search agents…"
        leftSection={<IconSearch size={14} />}
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
        maw={320}
      />

      <DataTable
        withTableBorder
        borderRadius="md"
        highlightOnHover
        minHeight={rows.length === 0 ? 160 : undefined}
        fetching={loading}
        records={rows}
        noRecordsText="No agents yet — create one above."
        sortStatus={sortStatus}
        onSortStatusChange={setSortStatus}
        columns={[
          {
            accessor: 'name',
            title: 'Name',
            sortable: true,
            render: (agent) => (
              <Link to={`/agents/${agent.id}`} style={{ fontWeight: 600, color: 'inherit' }}>
                {agent.name}
              </Link>
            ),
          },
          {
            accessor: 'online',
            title: 'Status',
            sortable: true,
            render: (agent) => (
              <Group gap={6} wrap="nowrap">
                <Indicator color={agent.online ? 'teal' : 'gray'} size={9} processing={agent.online} />
                <Text size="sm">{agent.online ? 'Online' : 'Offline'}</Text>
              </Group>
            ),
          },
          {
            accessor: 'last_seen_at',
            title: 'Last heartbeat',
            sortable: true,
            render: (agent) =>
              agent.last_seen_at ? (
                <Tooltip
                  label={`${new Date(agent.last_seen_at).toLocaleString()}${
                    agent.last_heartbeat_rtt_ms != null ? ` · ${agent.last_heartbeat_rtt_ms} ms RTT` : ''
                  }`}
                >
                  <Text size="sm" c="dimmed">
                    {dayjs(agent.last_seen_at).fromNow()}
                  </Text>
                </Tooltip>
              ) : (
                <Text size="sm" c="dimmed">
                  never
                </Text>
              ),
          },
          {
            accessor: 'agent_version',
            title: 'Version',
            render: (agent) => (agent.agent_version ? <Badge variant="light">{agent.agent_version}</Badge> : <Text c="dimmed">—</Text>),
          },
          {
            accessor: 'actions',
            title: '',
            textAlign: 'right',
            render: (agent) => (
              <Menu withinPortal position="bottom-end">
                <Menu.Target>
                  <ActionIcon variant="subtle" onClick={(e) => e.stopPropagation()}>
                    <IconDots size={16} />
                  </ActionIcon>
                </Menu.Target>
                <Menu.Dropdown>
                  <Menu.Item component={Link} to={`/agents/${agent.id}`}>
                    View log sources
                  </Menu.Item>
                  <Menu.Item onClick={() => setEditingAgent(agent)}>Rename</Menu.Item>
                  <Menu.Item leftSection={<IconKey size={14} />} onClick={() => handleReissue(agent)}>
                    Reissue token
                  </Menu.Item>
                  <Menu.Divider />
                  <Menu.Item color="red" leftSection={<IconTrash size={14} />} onClick={() => handleDelete(agent)}>
                    Delete
                  </Menu.Item>
                </Menu.Dropdown>
              </Menu>
            ),
          },
        ]}
      />

      {creating && (
        <Modal onClose={() => setCreating(false)}>
          <AgentForm onSubmit={handleCreate} onCancel={() => setCreating(false)} />
        </Modal>
      )}

      {editingAgent && (
        <Modal onClose={() => setEditingAgent(null)}>
          <AgentForm editingAgent={editingAgent} onSubmit={handleRename} onCancel={() => setEditingAgent(null)} />
        </Modal>
      )}

      {revealedToken && (
        <Modal onClose={() => setRevealedToken(null)} title={`Token for "${revealedToken.agent.name}"`}>
          <Stack gap="sm">
            <Text size="sm" c="dimmed">
              Shown once — copy it now and paste it into the agent's config
              (<code>LOGSONFIRE_AGENT_TOKEN</code> or <code>token</code> in{' '}
              <code>/etc/logsonfire-agent/config.toml</code>). It cannot be
              recovered later, only reissued.
            </Text>
            <Group wrap="nowrap" gap="xs">
              <Text component="code" style={{ flex: 1, wordBreak: 'break-all' }} bg="var(--mantine-color-default-hover)" p="xs" fz="sm">
                {revealedToken.token}
              </Text>
              <CopyButton value={revealedToken.token}>
                {({ copied, copy }) => (
                  <Button onClick={copy} color={copied ? 'teal' : 'flame'} size="xs">
                    {copied ? 'Copied' : 'Copy'}
                  </Button>
                )}
              </CopyButton>
            </Group>
            <Button onClick={() => setRevealedToken(null)} variant="default">
              I've copied it
            </Button>
          </Stack>
        </Modal>
      )}
    </Stack>
  )
}
