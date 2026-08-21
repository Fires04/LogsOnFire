export interface Agent {
  id: string
  name: string
  notes: string | null
  online: boolean
  last_seen_at: string | null
  last_heartbeat_rtt_ms: number | null
  agent_version: string | null
  server_version_mismatch: boolean
  token_prefix: string
}

export interface HealthInfo {
  status: string
  version: string
}

export interface AgentCreateInput {
  name: string
  notes?: string
}

export interface AgentUpdateInput {
  name?: string
  notes?: string
}

export interface TriggerUpdateResult {
  started: boolean
  error: string | null
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

export type LogSourceMode = 'exact_path' | 'glob' | 'regex' | 'journal' | 'docker'

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

export interface JournalUnitsResponse {
  units: string[]
  error: string | null
}

export interface DockerContainersResponse {
  containers: string[]
  error: string | null
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

export interface SavedFilter {
  id: string
  label: string
  expression: string
}

export interface SavedFilterCreateInput {
  label: string
  expression: string
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
