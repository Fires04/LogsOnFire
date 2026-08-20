import { useState, type FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { Alert, Button, Center, Paper, PasswordInput, Stack, Text, TextInput, ThemeIcon, Title } from '@mantine/core'
import { IconAlertCircle, IconFlame } from '@tabler/icons-react'
import { useAuth } from '../lib/auth'
import { ApiError } from '../lib/api'

export default function LoginPage() {
  const { user, login } = useAuth()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) {
    const from = (location.state as { from?: string } | null)?.from ?? '/agents'
    return <Navigate to={from} replace />
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(email, password)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Center mih="100vh" p="md">
      <Paper component="form" onSubmit={onSubmit} withBorder shadow="md" p="xl" radius="md" w="100%" maw={380}>
        <Stack align="center" gap={4} mb="md">
          <ThemeIcon size={56} radius="xl" variant="light" color="flame">
            <IconFlame size={32} />
          </ThemeIcon>
          <Title order={2}>Logs On Fire</Title>
          <Text c="dimmed" size="sm">
            Sign in to manage agents and logs.
          </Text>
        </Stack>
        <Stack gap="sm">
          <TextInput
            label="Email"
            type="email"
            required
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.currentTarget.value)}
          />
          <PasswordInput
            label="Password"
            required
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
          />
          {error && (
            <Alert icon={<IconAlertCircle size={16} />} color="red" variant="light">
              {error}
            </Alert>
          )}
          <Button type="submit" loading={busy} fullWidth mt="xs">
            Sign in
          </Button>
        </Stack>
      </Paper>
    </Center>
  )
}
