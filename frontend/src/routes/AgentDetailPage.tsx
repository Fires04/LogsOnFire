import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import dayjs from 'dayjs'
import { DataTable } from 'mantine-datatable'
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Drawer,
  Group,
  Indicator,
  ScrollArea,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import {
  IconAlertTriangle,
  IconArrowLeft,
  IconEye,
  IconExternalLink,
  IconListSearch,
  IconMaximize,
  IconMinimize,
  IconPencil,
  IconRefresh,
  IconSearch,
  IconTrash,
} from '@tabler/icons-react'
import { api, ApiError } from '../lib/api'
import { httpBase } from '../lib/serverOrigin'
import CopyField from '../components/CopyField'
import LogSourceForm from '../components/LogSourceForm'
import LogSourceViewer from '../components/LogSourceViewer'
import Modal from '../components/Modal'
import type { Agent, LogSource, LogSourceCreateInput, ResolveResponse, TriggerUpdateResult } from '../types/models'

const MODE_LABEL: Record<LogSource['mode'], string> = {
  exact_path: 'exact path',
  glob: 'glob',
  regex: 'regex',
  journal: 'journal',
  docker: 'docker',
}
const MODE_COLOR: Record<LogSource['mode'], string> = {
  exact_path: 'blue',
  glob: 'grape',
  regex: 'orange',
  journal: 'teal',
  docker: 'indigo',
}

/** One entry per actual file a log source resolves to (a glob/regex source
 * contributes one per match; exact_path/journal/docker contribute exactly
 * one each) — flattened across every log source on the agent for the "Log
 * files" quick-open list. */
interface FlatLogFile {
  sourceId: string
  sourceLabel: string
  path: string
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
  const [viewingResolvedPath, setViewingResolvedPath] = useState<string | undefined>(undefined)
  const [viewerExpanded, setViewerExpanded] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [addingOpen, setAddingOpen] = useState(false)
  const [allFiles, setAllFiles] = useState<FlatLogFile[] | null>(null)
  const [allFilesFilter, setAllFilesFilter] = useState('')
  const [notesDraft, setNotesDraft] = useState('')
  const [savingNotes, setSavingNotes] = useState(false)
  const [triggeringUpdate, setTriggeringUpdate] = useState(false)

  const refresh = useCallback(async () => {
    if (!agentId) return
    const [a, ls] = await Promise.all([
      api.get<Agent>(`/api/agents/${agentId}`),
      api.get<LogSource[]>(`/api/agents/${agentId}/log-sources`),
    ])
    setAgent(a)
    setSources(ls)
    setNotesDraft((prev) => (document.activeElement?.id === 'agent-notes' ? prev : a.notes ?? ''))
  }, [agentId])

  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [refresh])

  // Flat "Log files" list: resolve every log source in parallel so it's
  // one click straight to a live view, no per-source "Show matches" detour.
  // exact_path is self-resolving (no agent round-trip needed); glob/regex/
  // journal/docker all go through the same resolve endpoint the per-row
  // "Show matches" action already uses — for journal/docker it happens to
  // return exactly one file, already correctly prefixed
  // (journal://.../docker://...), so no mode-specific handling needed here.
  useEffect(() => {
    if (!agentId) return
    if (sources.length === 0) {
      setAllFiles([])
      return
    }
    let cancelled = false
    setAllFiles(null)
    Promise.all(
      sources.map(async (s): Promise<FlatLogFile[]> => {
        if (s.mode === 'exact_path') {
          return [{ sourceId: s.id, sourceLabel: s.label, path: s.path_or_pattern }]
        }
        try {
          const result = await api.post<ResolveResponse>(`/api/agents/${agentId}/log-sources/${s.id}/resolve`)
          if (result.error) return []
          return result.files.map((f) => ({ sourceId: s.id, sourceLabel: s.label, path: f.path }))
        } catch {
          return []
        }
      }),
    ).then((groups) => {
      if (!cancelled) setAllFiles(groups.flat())
    })
    return () => {
      cancelled = true
    }
  }, [agentId, sources])

  const filteredAllFiles = useMemo(() => {
    if (!allFiles) return null
    const needle = allFilesFilter.trim().toLowerCase()
    return needle
      ? allFiles.filter((f) => f.path.toLowerCase().includes(needle) || f.sourceLabel.toLowerCase().includes(needle))
      : allFiles
  }, [allFiles, allFilesFilter])

  function openResolvedFile(f: FlatLogFile) {
    setViewingId(f.sourceId)
    setViewingResolvedPath(f.path)
  }

  async function handleSaveNotes() {
    setSavingNotes(true)
    try {
      const updated = await api.patch<Agent>(`/api/agents/${agentId}`, { notes: notesDraft })
      setAgent(updated)
    } finally {
      setSavingNotes(false)
    }
  }

  async function handleTriggerUpdate() {
    setTriggeringUpdate(true)
    try {
      const result = await api.post<TriggerUpdateResult>(`/api/agents/${agentId}/trigger-update`)
      if (result.started) {
        notifications.show({
          color: 'teal',
          title: 'Update triggered',
          message: "The agent is upgrading and will reconnect shortly — its version badge will turn green once it's back on the current build.",
        })
      } else {
        notifications.show({ color: 'red', title: 'Could not trigger update', message: result.error ?? 'Unknown error' })
      }
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Could not trigger update',
        message: err instanceof ApiError ? err.message : 'Unknown error',
      })
    } finally {
      setTriggeringUpdate(false)
    }
  }

  async function handleCreate(input: LogSourceCreateInput) {
    await api.post(`/api/agents/${agentId}/log-sources`, input)
    await refresh()
  }

  async function handleUpdate(id: string, input: LogSourceCreateInput) {
    await api.patch(`/api/agents/${agentId}/log-sources/${id}`, input)
    await refresh()
    setEditingId(null)
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
          {agent.agent_version && (
            <Badge
              variant="light"
              color={agent.server_version_mismatch ? 'orange' : 'green'}
              rightSection={agent.server_version_mismatch ? <IconAlertTriangle size={11} /> : undefined}
            >
              {agent.agent_version}
            </Badge>
          )}
        </Group>
      </Card>

      <Card withBorder radius="md" p="md">
        <Stack gap="xs">
          <Textarea
            id="agent-notes"
            label="Notes"
            description="Rack/VM/role, anything that helps you tell agents apart — visible only here"
            value={notesDraft}
            onChange={(e) => setNotesDraft(e.currentTarget.value)}
            autosize
            minRows={2}
            placeholder="No notes yet"
          />
          <Group justify="flex-end">
            <Button
              size="xs"
              variant="default"
              onClick={handleSaveNotes}
              loading={savingNotes}
              disabled={notesDraft === (agent.notes ?? '')}
            >
              Save notes
            </Button>
          </Group>
        </Stack>
      </Card>

      {agent.server_version_mismatch && (
        <Alert icon={<IconAlertTriangle size={16} />} color="orange" variant="light" title="Agent needs an upgrade">
          <Stack gap="xs">
            <Text size="sm">
              This agent's version ({agent.agent_version}) doesn't match the server's. Trigger it remotely, or run
              this on the agent's own host (SSH into it first):
            </Text>
            <Group wrap="nowrap" align="flex-start" gap="xs">
              <Button
                size="xs"
                leftSection={<IconRefresh size={14} />}
                onClick={handleTriggerUpdate}
                loading={triggeringUpdate}
                disabled={!agent.online}
              >
                Update now
              </Button>
            </Group>
            <CopyField value={`curl -fsSL ${httpBase()}/agent/upgrade.sh | sudo bash`} />
          </Stack>
        </Alert>
      )}

      {!agent.online && (
        <Alert icon={<IconAlertTriangle size={16} />} color="yellow" variant="light">
          Agent is offline — browsing files and resolving patterns will fail until it reconnects.
        </Alert>
      )}

      <Card withBorder radius="md" p="md">
        <Stack gap="xs">
          <Title order={4}>Log files</Title>
          <Text c="dimmed" size="sm">
            Every file every log source below currently resolves to — click one to open it live.
          </Text>
          {(allFiles === null || allFiles.length > 8) && (
            <TextInput
              placeholder="Filter…"
              leftSection={<IconSearch size={14} />}
              value={allFilesFilter}
              onChange={(e) => setAllFilesFilter(e.currentTarget.value)}
            />
          )}
          {allFiles === null ? (
            <Text c="dimmed" size="sm">
              Resolving…
            </Text>
          ) : allFiles.length === 0 ? (
            <Text c="dimmed" size="sm">
              No log sources yet — add one below.
            </Text>
          ) : filteredAllFiles && filteredAllFiles.length === 0 ? (
            <Text c="dimmed" size="sm">
              No files match "{allFilesFilter}".
            </Text>
          ) : (
            <ScrollArea.Autosize mah={280}>
              <Stack gap={4}>
                {filteredAllFiles?.map((f) => (
                  <Button
                    key={`${f.sourceId}:${f.path}`}
                    variant="default"
                    justify="space-between"
                    fullWidth
                    rightSection={
                      <Badge variant="light" size="xs">
                        {f.sourceLabel}
                      </Badge>
                    }
                    onClick={() => openResolvedFile(f)}
                    styles={{ label: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }}
                  >
                    {f.path}
                  </Button>
                ))}
              </Stack>
            </ScrollArea.Autosize>
          )}
        </Stack>
      </Card>

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
                  <ActionIcon
                    variant="subtle"
                    onClick={() => {
                      setViewingId(s.id)
                      setViewingResolvedPath(undefined)
                    }}
                  >
                    <IconEye size={16} />
                  </ActionIcon>
                </Tooltip>
                <Tooltip label="Show matches">
                  <ActionIcon variant="subtle" onClick={() => handleResolve(s.id)} loading={resolving[s.id]}>
                    <IconListSearch size={16} />
                  </ActionIcon>
                </Tooltip>
                <Tooltip label="Edit">
                  <ActionIcon variant="subtle" onClick={() => setEditingId(s.id)}>
                    <IconPencil size={16} />
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

      {agentId && (
        <Button variant="default" onClick={() => setAddingOpen(true)} style={{ alignSelf: 'flex-start' }}>
          + Add log source
        </Button>
      )}

      {addingOpen && agentId && (
        // No Modal `title` here — LogSourceForm already renders its own
        // "Add log source" heading inside the Paper.
        <Modal onClose={() => setAddingOpen(false)} wide>
          <LogSourceForm
            agentId={agentId}
            onSubmit={async (input) => {
              await handleCreate(input)
              setAddingOpen(false)
            }}
          />
        </Modal>
      )}

      {editingId && agentId && (
        // No Modal `title` here — LogSourceForm already renders its own
        // "Edit log source" heading inside the Paper, same as "Add log
        // source" does inline; a second Modal-chrome title would duplicate it.
        <Modal onClose={() => setEditingId(null)} wide>
          <LogSourceForm
            agentId={agentId}
            initial={sources.find((s) => s.id === editingId)}
            onSubmit={(input) => handleUpdate(editingId, input)}
          />
        </Modal>
      )}

      <Drawer
        opened={viewingId !== null}
        onClose={() => {
          setViewingId(null)
          setViewingResolvedPath(undefined)
          setViewerExpanded(false)
        }}
        position="right"
        size={viewerExpanded ? '100%' : '60%'}
        title={
          <Group gap="sm">
            <Text fw={600}>{sources.find((s) => s.id === viewingId)?.label}</Text>
            <Tooltip label={viewerExpanded ? 'Shrink' : 'Expand to full width'}>
              <ActionIcon variant="subtle" size="sm" onClick={() => setViewerExpanded((v) => !v)}>
                {viewerExpanded ? <IconMinimize size={14} /> : <IconMaximize size={14} />}
              </ActionIcon>
            </Tooltip>
            {viewingId && (
              <Link to={`/view/log/${viewingId}`} target="_blank" rel="noreferrer" style={{ color: 'var(--mantine-color-dimmed)' }}>
                <IconExternalLink size={14} style={{ verticalAlign: -2 }} /> open in new window
              </Link>
            )}
          </Group>
        }
      >
        {viewingId && (
          <div style={{ height: 'calc(100vh - 100px)', display: 'flex' }}>
            <LogSourceViewer logSourceId={viewingId} initialResolvedPath={viewingResolvedPath} />
          </div>
        )}
      </Drawer>
    </Stack>
  )
}
