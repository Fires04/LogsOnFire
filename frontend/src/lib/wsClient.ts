/**
 * Multiplexed, auto-reconnecting WebSocket client for live log tailing.
 *
 * One `LogWsClient` instance is shared per browser tab/page (see the
 * `logWsClient` singleton below) so a standalone log view uses exactly one
 * WebSocket connection, and a dashboard with N panels — possibly across
 * several hosts — still uses exactly one, with N `subscribe` messages
 * multiplexed over it. Connection/process-level de-duplication on the
 * server (ssh/pool.py, tailing/manager.py) is what keeps the *backend*
 * resource usage minimal regardless of this client-side topology.
 *
 * Subscriptions are identified by a stable client-side id that outlives any
 * single WebSocket connection: on an unexpected disconnect, the client
 * reconnects with exponential backoff and transparently re-subscribes
 * everything (including re-applying any active grep filter) — callers never
 * see the underlying server subscription id change.
 */

export interface FilteredLine {
  line_no: number | null
  text: string
  is_match: boolean
  is_separator: boolean
}

export type LogEvent =
  | { type: 'backfill'; lines: string[] }
  | { type: 'line'; text: string }
  | { type: 'filtered_snapshot'; lines: FilteredLine[] }
  | { type: 'filter_error'; message: string }
  | { type: 'error'; message: string }
  | { type: 'closed'; reason: string }
  | { type: 'reconnecting' }

type Listener = (event: LogEvent) => void

interface ClientSubscription {
  logSourceId: string
  resolvedPath?: string
  listener: Listener
  serverSubId: string | null
  filterExpression: string | null
}

const RECONNECT_BASE_DELAY_MS = 500
const RECONNECT_MAX_DELAY_MS = 15000

class LogWsClient {
  private ws: WebSocket | null = null
  private connecting: Promise<void> | null = null
  private subscriptions = new Map<string, ClientSubscription>()
  private serverToClient = new Map<string, string>()
  private pendingByReqId = new Map<string, { clientId: string; resolve: () => void; reject: (err: Error) => void }>()
  private reqCounter = 0
  private clientIdCounter = 0
  private reconnectAttempt = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null

  private connect(): Promise<void> {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return Promise.resolve()
    if (this.connecting) return this.connecting

    this.connecting = new Promise((resolve, reject) => {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${window.location.host}/ws/logs`)
      this.ws = ws

      ws.onopen = () => {
        this.connecting = null
        this.reconnectAttempt = 0
        this.resubscribeAll()
        resolve()
      }
      ws.onerror = () => {
        this.connecting = null
        reject(new Error('WebSocket connection failed'))
      }
      ws.onclose = () => {
        this.connecting = null
        this.ws = null
        this.serverToClient.clear()
        for (const sub of this.subscriptions.values()) sub.serverSubId = null
        for (const pending of this.pendingByReqId.values()) {
          pending.reject(new Error('WebSocket closed before subscription confirmed'))
        }
        this.pendingByReqId.clear()
        if (this.subscriptions.size > 0) this.scheduleReconnect()
      }
      ws.onmessage = (ev) => this.handleMessage(ev)
    })
    return this.connecting
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return
    const delay = Math.min(RECONNECT_MAX_DELAY_MS, RECONNECT_BASE_DELAY_MS * 2 ** this.reconnectAttempt)
    this.reconnectAttempt += 1
    for (const sub of this.subscriptions.values()) sub.listener({ type: 'reconnecting' })
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      if (this.subscriptions.size === 0) return
      this.connect().catch(() => this.scheduleReconnect())
    }, delay)
  }

  private resubscribeAll() {
    for (const [clientId, sub] of this.subscriptions) {
      this.sendSubscribe(clientId, sub)
    }
  }

  private sendSubscribe(clientId: string, sub: ClientSubscription) {
    const reqId = `r${++this.reqCounter}`
    this.pendingByReqId.set(reqId, {
      clientId,
      resolve: () => {
        if (sub.filterExpression && sub.serverSubId) {
          this.setFilter(clientId, sub.filterExpression)
        }
      },
      reject: (err) => sub.listener({ type: 'error', message: err.message }),
    })
    this.ws!.send(
      JSON.stringify({
        type: 'subscribe',
        req_id: reqId,
        log_source_id: sub.logSourceId,
        resolved_path: sub.resolvedPath,
      }),
    )
  }

  private async handleReauthRequired() {
    try {
      await fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' })
    } catch {
      // The socket is about to be closed by the server regardless; the
      // normal reconnect/backoff path below will retry with whatever
      // cookie ends up being valid (or keep failing loudly if none is).
    }
  }

  private handleMessage(ev: MessageEvent) {
    let msg: Record<string, unknown>
    try {
      msg = JSON.parse(ev.data)
    } catch {
      return
    }

    if (msg.type === 'subscribed') {
      const reqId = msg.req_id as string
      const pending = this.pendingByReqId.get(reqId)
      if (pending) {
        this.pendingByReqId.delete(reqId)
        const subId = msg.subscription_id as string
        const sub = this.subscriptions.get(pending.clientId)
        if (sub) {
          sub.serverSubId = subId
          this.serverToClient.set(subId, pending.clientId)
          pending.resolve()
        }
      }
      return
    }

    if (msg.type === 'error' && msg.req_id && !msg.subscription_id) {
      const reqId = msg.req_id as string
      const pending = this.pendingByReqId.get(reqId)
      if (pending) {
        this.pendingByReqId.delete(reqId)
        pending.reject(new Error((msg.message as string) ?? 'subscribe failed'))
      }
      return
    }

    if (msg.type === 'pong') return
    if (msg.type === 'reauth_required') {
      void this.handleReauthRequired()
      return
    }

    const serverSubId = msg.subscription_id as string | undefined
    if (serverSubId) {
      const clientId = this.serverToClient.get(serverSubId)
      const sub = clientId ? this.subscriptions.get(clientId) : undefined
      sub?.listener(msg as unknown as LogEvent)
    }
  }

  /** Returns a stable client-side subscription id — pass it to unsubscribe/setFilter/clearFilter. */
  subscribe(logSourceId: string, resolvedPath: string | undefined, listener: Listener): string {
    const clientId = `c${++this.clientIdCounter}`
    const sub: ClientSubscription = {
      logSourceId,
      resolvedPath,
      listener,
      serverSubId: null,
      filterExpression: null,
    }
    this.subscriptions.set(clientId, sub)
    this.connect()
      .then(() => this.sendSubscribe(clientId, sub))
      .catch((err: Error) => listener({ type: 'error', message: err.message }))
    return clientId
  }

  unsubscribe(clientId: string) {
    const sub = this.subscriptions.get(clientId)
    if (!sub) return
    this.subscriptions.delete(clientId)
    if (sub.serverSubId) {
      this.serverToClient.delete(sub.serverSubId)
      this.send({ type: 'unsubscribe', subscription_id: sub.serverSubId })
    }
  }

  setFilter(clientId: string, expression: string) {
    const sub = this.subscriptions.get(clientId)
    if (!sub) return
    sub.filterExpression = expression
    if (sub.serverSubId) this.send({ type: 'set_filter', subscription_id: sub.serverSubId, expression })
  }

  clearFilter(clientId: string) {
    const sub = this.subscriptions.get(clientId)
    if (!sub) return
    sub.filterExpression = null
    if (sub.serverSubId) this.send({ type: 'clear_filter', subscription_id: sub.serverSubId })
  }

  private send(msg: object) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
    }
  }
}

/** One shared connection per browser tab — import this, don't instantiate LogWsClient yourself. */
export const logWsClient = new LogWsClient()
