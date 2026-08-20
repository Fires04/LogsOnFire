import { useEffect, useState } from 'react'
import { ActionIcon, Anchor, Breadcrumbs, Button, Group, ScrollArea, Stack, Table, Text, Title } from '@mantine/core'
import { IconArrowUp, IconFile, IconFolder, IconLock } from '@tabler/icons-react'
import { api } from '../lib/api'
import type { BrowseResponse, DirEntry } from '../types/models'

interface Props {
  agentId: string
  /** Called when the user picks a file. */
  onSelectFile: (path: string) => void
  /** Called when the user picks a directory via "Use this folder" (for regex base dir / glob base). */
  onSelectDirectory?: (path: string) => void
  onClose: () => void
}

export default function FileExplorer({ agentId, onSelectFile, onSelectDirectory, onClose }: Props) {
  const [data, setData] = useState<BrowseResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [requestError, setRequestError] = useState<string | null>(null)

  const load = (path?: string) => {
    setLoading(true)
    setRequestError(null)
    const query = path ? `?path=${encodeURIComponent(path)}` : ''
    api
      .get<BrowseResponse>(`/api/agents/${agentId}/browse${query}`)
      .then(setData)
      .catch((err: Error) => setRequestError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId])

  function handleEntryClick(entry: DirEntry) {
    if (entry.is_dir) {
      load(entry.path)
    } else {
      onSelectFile(entry.path)
    }
  }

  /** Splits "/var/log/nginx" into clickable crumbs: [{label: "/", path: "/"},
   * {label: "var", path: "/var"}, {label: "log", path: "/var/log"}, ...] —
   * lets you jump straight to an ancestor instead of clicking "Up" repeatedly. */
  function pathCrumbs(path: string): { label: string; path: string }[] {
    const segments = path.split('/').filter(Boolean)
    const crumbs = [{ label: '/', path: '/' }]
    let acc = ''
    for (const seg of segments) {
      acc += `/${seg}`
      crumbs.push({ label: seg, path: acc })
    }
    return crumbs
  }

  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Title order={4}>Browse files</Title>
        <Button variant="default" size="xs" onClick={onClose}>
          Close
        </Button>
      </Group>

      {data && (
        <Group gap="xs" wrap="nowrap">
          <ActionIcon variant="default" onClick={() => data.parent && load(data.parent)} disabled={!data.parent}>
            <IconArrowUp size={16} />
          </ActionIcon>
          <ScrollArea type="auto" style={{ flex: 1 }} scrollbarSize={6}>
            <Breadcrumbs separator="/" style={{ whiteSpace: 'nowrap' }}>
              {pathCrumbs(data.path).map((crumb) => (
                <Anchor key={crumb.path} component="button" type="button" fz="sm" ff="monospace" onClick={() => load(crumb.path)}>
                  {crumb.label}
                </Anchor>
              ))}
            </Breadcrumbs>
          </ScrollArea>
          {onSelectDirectory && (
            <Button size="xs" onClick={() => onSelectDirectory(data.path)}>
              Use this folder
            </Button>
          )}
        </Group>
      )}

      {loading && <Text c="dimmed">Loading…</Text>}
      {requestError && <Text c="red">{requestError}</Text>}
      {data?.error && <Text c="red">{data.error}</Text>}

      {data && !loading && !data.error && (
        <ScrollArea.Autosize mah="50vh">
          <Table highlightOnHover verticalSpacing={4}>
            <Table.Tbody>
              {data.entries.length === 0 && (
                <Table.Tr>
                  <Table.Td colSpan={3}>
                    <Text c="dimmed">Empty directory.</Text>
                  </Table.Td>
                </Table.Tr>
              )}
              {data.entries.map((entry) => (
                <Table.Tr
                  key={entry.path}
                  onClick={() => handleEntryClick(entry)}
                  style={{ cursor: 'pointer', opacity: entry.readable === false ? 0.6 : 1 }}
                  title={entry.readable === false ? 'You likely do not have read access to this file' : undefined}
                >
                  <Table.Td w={24}>{entry.is_dir ? <IconFolder size={16} /> : <IconFile size={16} />}</Table.Td>
                  <Table.Td>{entry.name}</Table.Td>
                  <Table.Td>
                    {entry.permissions && (
                      <Text component="code" fz="xs" c="dimmed">
                        {entry.permissions}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td ta="right">
                    {entry.readable === false ? (
                      <IconLock size={14} color="var(--mantine-color-red-6)" />
                    ) : !entry.is_dir && typeof entry.size === 'number' ? (
                      <Text fz="xs" c="dimmed">
                        {entry.size.toLocaleString()} B
                      </Text>
                    ) : null}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          {data.truncated && (
            <Text c="dimmed" fz="sm" mt="xs">
              List truncated — narrow it down by navigating deeper.
            </Text>
          )}
        </ScrollArea.Autosize>
      )}
    </Stack>
  )
}
