/** Typed fetch wrapper: same-origin cookies, CSRF header on mutations, JSON in/out. */

export function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'))
  return match ? decodeURIComponent(match[1]) : null
}

export class ApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, body: unknown, message: string) {
    super(message)
    this.status = status
    this.body = body
  }
}

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

/** A 401 on an access token that just expired (15 min by default) doesn't
 * have to mean "log in again" — a refresh token cookie (7-30 days,
 * see "remember me") usually still covers it. Concurrent requests that all
 * 401 at once (e.g. a dashboard's several panels loading together) must
 * only trigger one /api/auth/refresh, not a stampede — every caller awaits
 * this same in-flight promise. */
let refreshInFlight: Promise<boolean> | null = null

async function tryRefresh(): Promise<boolean> {
  if (!refreshInFlight) {
    // /api/auth/refresh is a POST under /api/ and NOT in the backend's
    // CsrfMiddleware EXEMPT_PATHS (only /api/auth/login is) — it needs the
    // CSRF header like any other mutation, or the backend 403s it before
    // it ever gets a chance to actually refresh anything.
    const csrf = getCookie('csrf_token')
    refreshInFlight = fetch('/api/auth/refresh', {
      method: 'POST',
      credentials: 'include',
      headers: csrf ? { 'X-CSRF-Token': csrf } : undefined,
    })
      .then((resp) => resp.ok)
      .catch(() => false)
      .finally(() => {
        refreshInFlight = null
      })
  }
  return refreshInFlight
}

export async function apiFetch<T>(path: string, init: RequestInit = {}, _isRetry = false): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (!SAFE_METHODS.has(method)) {
    const csrf = getCookie('csrf_token')
    if (csrf) headers.set('X-CSRF-Token', csrf)
  }
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const resp = await fetch(path, { ...init, method, headers, credentials: 'include' })

  if (resp.status === 401 && !path.startsWith('/api/auth/')) {
    // Only ever try the silent-refresh-and-retry path once per call, and
    // never for the refresh request itself (checked above) — otherwise a
    // truly dead session would loop.
    if (!_isRetry && (await tryRefresh())) {
      return apiFetch<T>(path, init, true)
    }
    // Refresh token is gone/expired too — this really is "log in again".
    // The caller's promise never resolves meaningfully after this; a full
    // navigation is the simplest correct behaviour for a tool like this.
    window.location.href = '/login'
    return new Promise<T>(() => {})
  }

  const isJson = resp.headers.get('content-type')?.includes('application/json')
  const data = isJson ? await resp.json().catch(() => null) : null

  if (!resp.ok) {
    const message = (data && typeof data === 'object' && 'detail' in data && String((data as { detail: unknown }).detail)) || resp.statusText
    throw new ApiError(resp.status, data, message)
  }
  return data as T
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, { method: 'PATCH', body: body !== undefined ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => apiFetch<T>(path, { method: 'DELETE' }),
}
