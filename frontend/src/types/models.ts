export type ConnectionType = 'local' | 'ssh'
export type AuthType = 'password' | 'private_key'

export interface Host {
  id: string
  name: string
  connection_type: ConnectionType
  hostname: string | null
  port: number
  ssh_username: string | null
  auth_type: AuthType | null
  has_password: boolean
  has_private_key: boolean
}

export interface HostCreateInput {
  name: string
  connection_type: ConnectionType
  hostname?: string
  port?: number
  ssh_username?: string
  auth_type?: AuthType
  password?: string
  private_key?: string
  private_key_passphrase?: string
}

export interface HostUpdateInput {
  name?: string
  hostname?: string
  port?: number
  ssh_username?: string
  auth_type?: AuthType
  password?: string
  private_key?: string
  private_key_passphrase?: string
}

export interface TestConnectionResult {
  success: boolean
  message: string
}

export type LogSourceMode = 'exact_path' | 'glob' | 'regex' | 'journal'

export interface LogSource {
  id: string
  host_id: string
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
