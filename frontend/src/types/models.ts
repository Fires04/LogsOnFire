export interface Agent {
  id: string
  name: string
  online: boolean
  last_seen_at: string | null
  last_heartbeat_rtt_ms: number | null
  agent_version: string | null
  token_prefix: string
}

export interface AgentCreateInput {
  name: string
}

export interface AgentUpdateInput {
  name?: string
}

/** Returned only from enrollment/reissue — `token` is shown exactly once. */
export interface AgentCreateResult {
  agent: Agent
  token: string
}

export interface InstallLinkCreateInput {
  token: string
  server_url: string
}

export interface InstallLinkResult {
  code: string
  expires_in_seconds: number
}

export type LogSourceMode = 'exact_path' | 'glob' | 'regex' | 'journal'

export interface LogSource {
  id: string
  agent_id: string
  label: string
  mode: LogSourceMode
  path_or_pattern: string
  regex_base_dir: string | null
}

export interface LogSourceCreateInput {
  label: string
  mode: LogSourceMode
  path_or_pattern: string
  regex_base_dir?: string
}

export interface ResolvedFile {
  path: string
  size: number | null
  mtime: number | null
}

export interface ResolveResponse {
  files: ResolvedFile[]
  truncated: boolean
  error: string | null
  warning: string | null
}

export interface DashboardPanel {
  id: string
  log_source_id: string
  resolved_path: string | null
  position_x: number
  position_y: number
  width: number
  height: number
  display_order: number
}

export interface DashboardPanelCreate {
  log_source_id: string
  resolved_path?: string
  position_x?: number
  position_y?: number
  width?: number
  height?: number
  display_order?: number
}

export interface Dashboard {
  id: string
  name: string
  owner_id: string | null
  panels: DashboardPanel[]
}

export interface Me {
  id: string
  email: string
  is_admin: boolean
}

export interface DirEntry {
  name: string
  path: string
  is_dir: boolean
  size: number | null
  mtime: number | null
  permissions: string | null
  readable: boolean | null
}

export interface BrowseResponse {
  path: string
  parent: string | null
  entries: DirEntry[]
  truncated: boolean
  error: string | null
}
