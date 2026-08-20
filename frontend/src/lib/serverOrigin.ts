/** This server's own origin, derived from wherever the browser currently is
 * (localhost, a LAN hostname, a real domain behind a proxy — all handled
 * automatically) rather than configured separately. Shared by AgentsPage
 * (install commands) and AgentDetailPage (the upgrade-this-agent hint). */
export function httpBase(): string {
  return `${window.location.protocol}//${window.location.host}`
}

export function wsBase(): string {
  const isHttps = window.location.protocol === 'https:'
  return `${isHttps ? 'wss' : 'ws'}://${window.location.host}`
}
