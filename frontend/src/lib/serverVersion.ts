import { useEffect, useState } from 'react'
import { api } from './api'
import type { HealthInfo } from '../types/models'

/** GET /api/health is unauthenticated and cheap, but both the login screen
 * and the app shell's nav footer want it — a tiny module-level cache +
 * pub/sub (same pattern as lib/savedFilters.ts) avoids fetching it twice
 * on a normal login -> app navigation. The version can't change without a
 * redeploy, which reloads the page anyway, so there's no need to re-poll. */
let cache: string | null = null
let inflight: Promise<void> | null = null
const listeners = new Set<(version: string) => void>()

function ensureLoaded(): void {
  if (cache || inflight) return
  inflight = api
    .get<HealthInfo>('/api/health')
    .then((data) => {
      cache = data.version
      listeners.forEach((l) => l(cache!))
    })
    .catch(() => {})
    .finally(() => {
      inflight = null
    })
}

export function useServerVersion(): string | null {
  const [version, setVersion] = useState<string | null>(cache)
  useEffect(() => {
    listeners.add(setVersion)
    ensureLoaded()
    return () => {
      listeners.delete(setVersion)
    }
  }, [])
  return version
}
