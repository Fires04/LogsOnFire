import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import {
  ActionIcon,
  AppShell as MantineAppShell,
  Badge,
  Group,
  NavLink,
  Text,
  useMantineColorScheme,
} from '@mantine/core'
import { IconLogout, IconMoon, IconSun, IconTerminal2 } from '@tabler/icons-react'
import { useAuth } from '../lib/auth'
import { api } from '../lib/api'
import type { Agent } from '../types/models'

const AGENT_SUMMARY_POLL_MS = 15000

export default function AppShell() {
  const { user, logout } = useAuth()
  const { colorScheme, toggleColorScheme } = useMantineColorScheme()
  const [agentSummary, setAgentSummary] = useState<{ online: number; total: number } | null>(null)
  const location = useLocation()

  useEffect(() => {
    let cancelled = false
    async function poll() {
      try {
        const agents = await api.get<Agent[]>('/api/agents')
        if (!cancelled) setAgentSummary({ online: agents.filter((a) => a.online).length, total: agents.length })
      } catch {
        // ambient status widget — a failed poll just leaves the last known value
      }
    }
    poll()
    const id = setInterval(poll, AGENT_SUMMARY_POLL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  return (
    <MantineAppShell header={{ height: 56 }} navbar={{ width: 220, breakpoint: 'sm' }} padding="md">
      <MantineAppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <IconTerminal2 size={22} color="var(--mantine-color-flame-6)" />
            <Text fw={700}>Logs On Fire</Text>
          </Group>
          <Group gap="sm">
            {agentSummary && (
              <Badge
                variant="light"
                color={agentSummary.online === agentSummary.total && agentSummary.total > 0 ? 'teal' : 'gray'}
              >
                {agentSummary.online}/{agentSummary.total} agents online
              </Badge>
            )}
            <ActionIcon variant="subtle" onClick={() => toggleColorScheme()} aria-label="Toggle color scheme">
              {colorScheme === 'dark' ? <IconSun size={18} /> : <IconMoon size={18} />}
            </ActionIcon>
            <Text size="sm" c="dimmed">
              {user?.email}
            </Text>
            <ActionIcon variant="subtle" onClick={() => logout()} aria-label="Log out">
              <IconLogout size={18} />
            </ActionIcon>
          </Group>
        </Group>
      </MantineAppShell.Header>

      <MantineAppShell.Navbar p="sm">
        <NavLink component={Link} to="/agents" label="Agents" active={location.pathname.startsWith('/agents')} />
        <NavLink component={Link} to="/dashboards" label="Dashboards" active={location.pathname.startsWith('/dashboards')} />
      </MantineAppShell.Navbar>

      <MantineAppShell.Main>
        <Outlet />
      </MantineAppShell.Main>
    </MantineAppShell>
  )
}
