import { useEffect, useState } from 'react'
import { api } from './api'
import type { HealthInfo } from '../types/models'

/** GET /api/health is unauthenticated and cheap, but the login screen, the
 * app shell's nav footer, and (for oidc_enabled) the login screen again all
 * want it — a tiny module-level cache + pub/sub (same pattern as
 * lib/savedFilters.ts) avoids fetching it twice on a normal login -> app
 * navigation. Nothing in it can change without a redeploy, which reloads
 * the page anyway, so there's no need to re-poll. */
let cache: HealthInfo | null = null
let inflight: Promise<void> | null = null
const listeners = new Set<(info: HealthInfo) => void>()

function ensureLoaded(): void {
  if (cache || inflight) return
  inflight = api
    .get<HealthInfo>('/api/health')
    .then((data) => {
      cache = data
      listeners.forEach((l) => l(cache!))
    })
    .catch(() => {})
    .finally(() => {
      inflight = null
    })
}

function useHealthInfo(): HealthInfo | null {
  const [info, setInfo] = useState<HealthInfo | null>(cache)
  useEffect(() => {
    listeners.add(setInfo)
    ensureLoaded()
    return () => {
      listeners.delete(setInfo)
    }
  }, [])
  return info
}

export function useServerVersion(): string | null {
  return useHealthInfo()?.version ?? null
}

/** Whether the server has Authentik/OIDC login configured — the login page
 * uses this to decide whether to show the "Sign in with Authentik" link.
 * false (not just "unknown") until the health fetch resolves, so the link
 * never flashes in only to disappear. */
export function useOidcEnabled(): boolean {
  return useHealthInfo()?.oidc_enabled ?? false
}
