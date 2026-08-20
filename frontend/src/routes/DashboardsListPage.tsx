import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ActionIcon, Button, Card, Grid, Group, Paper, Stack, Text, TextInput, Title, Tooltip } from '@mantine/core'
import { IconExternalLink, IconPencil, IconPlus, IconTrash } from '@tabler/icons-react'
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
    <Stack gap="md">
      <Title order={2}>Dashboards</Title>

      <Grid>
        <Grid.Col span={{ base: 12, md: 8 }}>
          <Stack gap="sm">
            {loading ? (
              <Text c="dimmed">Loading…</Text>
            ) : dashboards.length === 0 ? (
              <Text c="dimmed">No dashboards yet. Create one on the right.</Text>
            ) : (
              dashboards.map((d) => (
                <Card key={d.id} withBorder radius="md" p="md">
                  <Group justify="space-between">
                    <div>
                      <Text fw={600}>{d.name}</Text>
                      <Text c="dimmed" size="sm">
                        {d.panels.length} panel{d.panels.length === 1 ? '' : 's'}
                      </Text>
                    </div>
                    <Group gap={4}>
                      <Tooltip label="Edit">
                        <ActionIcon component={Link} to={`/dashboards/${d.id}/edit`} variant="subtle">
                          <IconPencil size={16} />
                        </ActionIcon>
                      </Tooltip>
                      <Tooltip label="Open live">
                        <ActionIcon
                          component={Link}
                          to={`/view/dashboard/${d.id}`}
                          target="_blank"
                          rel="noreferrer"
                          variant="subtle"
                        >
                          <IconExternalLink size={16} />
                        </ActionIcon>
                      </Tooltip>
                      <Tooltip label="Delete">
                        <ActionIcon variant="subtle" color="red" onClick={() => handleDelete(d.id)}>
                          <IconTrash size={16} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Group>
                </Card>
              ))
            )}
          </Stack>
        </Grid.Col>

        <Grid.Col span={{ base: 12, md: 4 }}>
          <Paper component="form" onSubmit={handleCreate} withBorder p="md" radius="md">
            <Stack gap="sm">
              <Title order={4}>New dashboard</Title>
              <TextInput
                label="Name"
                value={name}
                onChange={(e) => setName(e.currentTarget.value)}
                required
                placeholder="e.g. Production"
              />
              <Button type="submit" leftSection={<IconPlus size={16} />}>
                Create and edit
              </Button>
            </Stack>
          </Paper>
        </Grid.Col>
      </Grid>
    </Stack>
  )
}
