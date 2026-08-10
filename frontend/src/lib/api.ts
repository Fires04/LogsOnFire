/** Typed fetch wrapper: same-origin cookies, CSRF header on mutations, JSON in/out. */

function getCookie(name: string): string | null {
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

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
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
    // Session expired/missing — bounce to login. The caller's promise never
    // resolves meaningfully after this; a full navigation is the simplest
    // correct behaviour for a tool like this.
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
