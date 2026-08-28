import { useState, type FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { Alert, Button, Center, Checkbox, Divider, Paper, PasswordInput, Stack, Text, TextInput, Title } from '@mantine/core'
import { IconAlertCircle, IconLogin2 } from '@tabler/icons-react'
import { useAuth } from '../lib/auth'
import { ApiError } from '../lib/api'
import { useOidcEnabled, useServerVersion } from '../lib/serverVersion'

export default function LoginPage() {
  const { user, login } = useAuth()
  const serverVersion = useServerVersion()
  const oidcEnabled = useOidcEnabled()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) {
    const from = (location.state as { from?: string } | null)?.from ?? '/agents'
    return <Navigate to={from} replace />
  }

  // Set by a redirect from GET /api/auth/oidc/callback when the Authentik
  // identity's email doesn't match any existing FiresLog account — surfaced
  // here rather than as a generic failed-login, since there's nothing to
  // retry: the account has to already exist first.
  const oidcUnmapped = new URLSearchParams(location.search).get('error') === 'oidc_unmapped'
  const displayError = error ?? (oidcUnmapped ? 'That Authentik account has no matching FiresLog user.' : null)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(email, password, remember)
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
          <img src="/logo.png" alt="" width={72} height={72} style={{ display: 'block', marginBottom: 4 }} />
          <Title order={2}>Logs On Fire</Title>
          <Text c="dimmed" size="sm">
            Sign in to manage agents and logs.
          </Text>
        </Stack>
        <Stack gap="sm">
          {/* name/autoComplete: password managers (Passbolt, Bitwarden, the
              browser's own) identify fields — and, critically, dispatch the
              synthetic input event React's controlled value actually
              picks up — largely via these attributes. Without them,
              autofill was seen to intermittently "fill" the input visually
              without ever firing onChange, so email/password stayed empty
              in state until the user typed something themselves. */}
          <TextInput
            label="Email"
            type="email"
            name="email"
            autoComplete="username"
            required
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.currentTarget.value)}
          />
          <PasswordInput
            label="Password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
          />
          <Checkbox
            label="Remember me on this device"
            checked={remember}
            onChange={(e) => setRemember(e.currentTarget.checked)}
          />
          {displayError && (
            <Alert icon={<IconAlertCircle size={16} />} color="red" variant="light">
              {displayError}
            </Alert>
          )}
          <Button type="submit" loading={busy} fullWidth mt="xs">
            Sign in
          </Button>
        </Stack>
        {oidcEnabled && (
          <>
            <Divider label="or" labelPosition="center" my="md" />
            <Button
              component="a"
              href="/api/auth/oidc/login"
              variant="default"
              fullWidth
              leftSection={<IconLogin2 size={16} />}
            >
              Sign in with Authentik
            </Button>
          </>
        )}
        {serverVersion && (
          <Text c="dimmed" size="xs" ta="center" mt="md">
            v{serverVersion}
          </Text>
        )}
      </Paper>
    </Center>
  )
}
