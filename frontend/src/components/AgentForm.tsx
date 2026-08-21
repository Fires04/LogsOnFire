import { useState, type FormEvent } from 'react'
import { Button, Group, Paper, Stack, Text, Textarea, TextInput, Title } from '@mantine/core'
import type { Agent, AgentCreateInput, AgentUpdateInput } from '../types/models'

interface Props {
  /** When set, the form renames this agent instead of creating a new one —
   * an agent's identity is otherwise fixed (no more connection fields to
   * edit, unlike the old SSH-era HostForm). */
  editingAgent?: Agent
  onSubmit: (input: AgentCreateInput | AgentUpdateInput) => Promise<void>
  onCancel?: () => void
}

export default function AgentForm({ editingAgent, onSubmit, onCancel }: Props) {
  const isEdit = !!editingAgent
  const [name, setName] = useState(editingAgent?.name ?? '')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await onSubmit(isEdit ? { name } : { name, notes: notes.trim() || undefined })
      if (!isEdit) {
        setName('')
        setNotes('')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to ${isEdit ? 'rename agent' : 'create agent'}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Paper component="form" onSubmit={handleSubmit} withBorder p="md" radius="md">
      <Stack gap="sm">
        <Title order={4}>{isEdit ? `Rename ${editingAgent!.name}` : 'New agent'}</Title>
        {!isEdit && (
          <Text size="sm" c="dimmed">
            Creates an identity and a one-time bearer token. Install the
            agent on the host you want to monitor and paste the token into
            its config — see <code>agent/install.sh</code>.
          </Text>
        )}
        <TextInput
          label="Name"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          required
          placeholder="e.g. web-01"
          autoFocus
        />
        {!isEdit && (
          <Textarea
            label="Notes"
            description="Optional — rack/VM/role, anything that helps you tell agents apart later"
            value={notes}
            onChange={(e) => setNotes(e.currentTarget.value)}
            autosize
            minRows={2}
          />
        )}
        {error && (
          <Text c="red" size="sm">
            {error}
          </Text>
        )}
        <Group>
          <Button type="submit" loading={busy}>
            {isEdit ? 'Save' : 'Create agent'}
          </Button>
          {onCancel && (
            <Button type="button" variant="default" onClick={onCancel} disabled={busy}>
              Cancel
            </Button>
          )}
        </Group>
      </Stack>
    </Paper>
  )
}
