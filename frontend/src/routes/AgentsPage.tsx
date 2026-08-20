import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { DataTable, type DataTableSortStatus } from 'mantine-datatable'
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Indicator,
  Menu,
  Popover,
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
  IconRefresh,
  IconSearch,
  IconTrash,
} from '@tabler/icons-react'
import { api, ApiError } from '../lib/api'
import { httpBase, wsBase } from '../lib/serverOrigin'
import AgentForm from '../components/AgentForm'
import CopyField from '../components/CopyField'
import Modal from '../components/Modal'
import type {
  Agent,
  AgentCreateInput,
  AgentCreateResult,
  AgentUpdateInput,
  InstallLinkResult,
} from '../types/models'

dayjs.extend(relativeTime)

/** The manual fallback one-liner (README's Quick start) — has the token as
 * a plain CLI argument, so it lands in the target host's shell history and
 * is briefly visible via `ps` while it runs. Only shown if the one-time
 * install link (below) couldn't be generated. */
function manualInstallCommand(token: string): string {
  return `curl -fsSL ${httpBase()}/agent/install.sh | sudo bash -s -- --server ${wsBase()} --token ${token}`
}

function oneTimeInstallCommand(code: string): string {
  return `curl -fsSL ${httpBase()}/agent/install/${code} | sudo bash`
}

function upgradeCommand(): string {
  return `curl -fsSL ${httpBase()}/agent/upgrade.sh | sudo bash`
}

/** Click-to-reveal upgrade instructions for a version-mismatched agent —
 * an icon rather than plain text/tooltip so there's an actual copy button,
 * not just something to read and retype. */
function UpgradeHint() {
  return (
    <Popover withinPortal position="bottom-end" shadow="md">
      <Popover.Target>
        <ActionIcon
          size="sm"
          variant="light"
          color="orange"
          title="Version doesn't match the server — click to upgrade"
          onClick={(e) => e.stopPropagation()}
        >
          <IconRefresh size={13} />
        </ActionIcon>
      </Popover.Target>
      <Popover.Dropdown maw={360}>
        <Stack gap="xs">
          <Text size="sm" fw={600}>
            Agent needs an upgrade
          </Text>
          <Text size="xs" c="dimmed">
            Run this on the agent's own host (SSH into it first):
          </Text>
          <CopyField value={upgradeCommand()} />
        </Stack>
      </Popover.Dropdown>
    </Popover>
  )
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [sortStatus, setSortStatus] = useState<DataTableSortStatus<Agent>>({ columnAccessor: 'name', direction: 'asc' })
  const [creating, setCreating] = useState(false)
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null)
  const [revealedToken, setRevealedToken] = useState<AgentCreateResult | null>(null)
  const [installLink, setInstallLink] = useState<InstallLinkResult | null>(null)
  const [installLinkError, setInstallLinkError] = useState<string | null>(null)
  const [installLinkLoading, setInstallLinkLoading] = useState(false)

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

  async function reveal(agentId: string, result: AgentCreateResult) {
    setRevealedToken(result)
    setInstallLink(null)
    setInstallLinkError(null)
    setInstallLinkLoading(true)
    try {
      // The token only ever exists in plaintext here in the browser and in
      // this one-shot response — the server never persisted it, so it has
      // to be handed back for the one-time install link to embed it.
      const link = await api.post<InstallLinkResult>(`/api/agents/${agentId}/install-link`, {
        token: result.token,
        server_url: wsBase(),
      })
      setInstallLink(link)
    } catch (err) {
      setInstallLinkError(err instanceof ApiError ? err.message : 'Failed to create an install link')
    } finally {
      setInstallLinkLoading(false)
    }
  }

  async function handleCreate(input: AgentCreateInput | AgentUpdateInput) {
    const result = await api.post<AgentCreateResult>('/api/agents', input as AgentCreateInput)
    setCreating(false)
    await reveal(result.agent.id, result)
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
    await reveal(agent.id, result)
    await refresh()
  }

  function closeRevealedToken() {
    setRevealedToken(null)
    setInstallLink(null)
    setInstallLinkError(null)
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
            render: (agent) =>
              agent.agent_version ? (
                agent.server_version_mismatch ? (
                  <Group gap={6} wrap="nowrap">
                    <Badge variant="light" color="orange">
                      {agent.agent_version}
                    </Badge>
                    <UpgradeHint />
                  </Group>
                ) : (
                  <Badge variant="light">{agent.agent_version}</Badge>
                )
              ) : (
                <Text c="dimmed">—</Text>
              ),
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
        <Modal onClose={closeRevealedToken} title={`Token for "${revealedToken.agent.name}"`} wide>
          <Stack gap="sm">
            <Text size="sm" c="dimmed">
              The token itself is shown once below — it cannot be recovered
              later, only reissued.
            </Text>

            <Text size="sm" fw={600}>
              Paste directly into an SSH session on the host to monitor:
            </Text>
            {installLinkLoading && (
              <Text size="sm" c="dimmed">
                Generating a one-time install link…
              </Text>
            )}
            {installLink && (
              <>
                <CopyField value={oneTimeInstallCommand(installLink.code)} />
                <Text size="xs" c="dimmed">
                  Single use, expires in {Math.round(installLink.expires_in_seconds / 60)} minutes — the
                  token itself never touches this host's shell history, only
                  this one-time (already-spent-after-use) link code does.
                </Text>
              </>
            )}
            {installLinkError && !installLinkLoading && (
              <>
                <Text size="sm" c="red">
                  Couldn't create a one-time link ({installLinkError}) — falling back to the direct
                  command below. This puts the token in the target host's shell history.
                </Text>
                <CopyField value={manualInstallCommand(revealedToken.token)} />
              </>
            )}

            <Text size="sm" c="dimmed" mt="xs">
              Or just the token, e.g. to edit <code>/etc/logsonfire-agent/config.toml</code> by hand:
            </Text>
            <CopyField value={revealedToken.token} />

            <Button onClick={closeRevealedToken} variant="default">
              I've copied it
            </Button>
          </Stack>
        </Modal>
      )}
    </Stack>
  )
}
