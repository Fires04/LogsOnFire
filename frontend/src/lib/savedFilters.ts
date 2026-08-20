import { useEffect, useState } from 'react'
import { api } from './api'
import type { SavedFilter, SavedFilterCreateInput } from '../types/models'

/** A dashboard can have many LogPanels mounted at once, each wanting the
 * same "my saved filters" list — a tiny module-level cache + pub/sub
 * avoids N duplicate GET requests on mount and keeps every panel's
 * dropdown in sync the moment one of them saves/deletes an entry. */
let cache: SavedFilter[] | null = null
let inflight: Promise<SavedFilter[]> | null = null
const listeners = new Set<(filters: SavedFilter[]) => void>()

function notify() {
  const filters = cache ?? []
  listeners.forEach((l) => l(filters))
}

function ensureLoaded(): void {
  if (cache || inflight) return
  inflight = api
    .get<SavedFilter[]>('/api/saved-filters')
    .then((data) => {
      cache = data
      notify()
      return data
    })
    .finally(() => {
      inflight = null
    })
}

export function useSavedFilters() {
  const [filters, setFilters] = useState<SavedFilter[]>(cache ?? [])

  useEffect(() => {
    listeners.add(setFilters)
    ensureLoaded()
    return () => {
      listeners.delete(setFilters)
    }
  }, [])

  async function save(input: SavedFilterCreateInput): Promise<SavedFilter> {
    const created = await api.post<SavedFilter>('/api/saved-filters', input)
    cache = [...(cache ?? []), created].sort((a, b) => a.label.localeCompare(b.label))
    notify()
    return created
  }

  async function remove(id: string): Promise<void> {
    await api.delete(`/api/saved-filters/${id}`)
    cache = (cache ?? []).filter((f) => f.id !== id)
    notify()
  }

  return { filters, save, remove }
}
