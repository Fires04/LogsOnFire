/** crypto.randomUUID() requires a "secure context" (HTTPS or localhost) —
 * on a plain-HTTP LAN deployment of this self-hosted tool (e.g.
 * http://pees:8000, no reverse proxy/TLS) it's missing entirely, and
 * unlike a normal missing-API check this throws "TypeError:
 * crypto.randomUUID is not a function" straight out of a render path,
 * which crashed the whole dashboard editor page (found by direct
 * testing — same class of bug as clipboard.ts's copy-over-plain-HTTP
 * fix). These ids are only used as ephemeral React keys for unsaved
 * draft panels, never persisted or security-sensitive, so a
 * cryptographically-random UUID isn't actually needed — fall back to a
 * plain Math.random()-based id when the real API isn't available. */
export function randomId(): string {
  if (window.isSecureContext && typeof crypto?.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}
