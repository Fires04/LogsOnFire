import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { BrowseResponse, DirEntry } from '../types/models'

interface Props {
  hostId: string
  /** Called when the user picks a file. */
  onSelectFile: (path: string) => void
  /** Called when the user picks a directory via "Use this folder" (for regex base dir / glob base). */
  onSelectDirectory?: (path: string) => void
  onClose: () => void
}

export default function FileExplorer({ hostId, onSelectFile, onSelectDirectory, onClose }: Props) {
  const [data, setData] = useState<BrowseResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [requestError, setRequestError] = useState<string | null>(null)

  const load = (path?: string) => {
    setLoading(true)
    setRequestError(null)
    const query = path ? `?path=${encodeURIComponent(path)}` : ''
    api
      .get<BrowseResponse>(`/api/hosts/${hostId}/browse${query}`)
      .then(setData)
      .catch((err: Error) => setRequestError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hostId])

  function handleEntryClick(entry: DirEntry) {
    if (entry.is_dir) {
      load(entry.path)
    } else {
      onSelectFile(entry.path)
    }
  }

  /** Splits "/var/log/nginx" into clickable crumbs: [{label: "/", path: "/"},
   * {label: "var", path: "/var"}, {label: "log", path: "/var/log"}, ...] —
   * lets you jump straight to an ancestor instead of clicking "Up" repeatedly. */
  function pathCrumbs(path: string): { label: string; path: string }[] {
    const segments = path.split('/').filter(Boolean)
    const crumbs = [{ label: '/', path: '/' }]
    let acc = ''
    for (const seg of segments) {
      acc += `/${seg}`
      crumbs.push({ label: seg, path: acc })
    }
    return crumbs
  }

  return (
    <div className="card file-explorer">
      <div className="file-explorer-header">
        <h2>Browse files</h2>
        <button type="button" className="secondary" onClick={onClose}>
          Close
        </button>
      </div>

      {data && (
        <div className="file-explorer-toolbar">
          <button type="button" className="secondary" onClick={() => data.parent && load(data.parent)} disabled={!data.parent}>
            ↑ Up
          </button>
          <code className="file-explorer-path">
            {pathCrumbs(data.path).map((crumb, i) => (
              // crumb 0 is "/" itself, which already supplies the leading
              // slash — only crumbs after the first real segment need one
              // prepended, so "/", "var", "log" renders as "/var/log", not "//var/log".
              <span key={crumb.path}>
                {i > 1 && '/'}
                <button type="button" className="file-explorer-crumb" onClick={() => load(crumb.path)}>
                  {crumb.label}
                </button>
              </span>
            ))}
          </code>
          {onSelectDirectory && (
            <button type="button" onClick={() => onSelectDirectory(data.path)}>
              Use this folder
            </button>
          )}
        </div>
      )}

      {loading && <p className="muted">Loading…</p>}
      {requestError && <p className="error">{requestError}</p>}
      {data?.error && <p className="error">{data.error}</p>}

      {data && !loading && !data.error && (
        <ul className="file-explorer-list">
          {data.entries.length === 0 && <li className="muted">Empty directory.</li>}
          {data.entries.map((entry) => (
            <li
              key={entry.path}
              className={
                entry.readable === false ? 'file-explorer-entry file-explorer-entry-unreadable' : 'file-explorer-entry'
              }
              onClick={() => handleEntryClick(entry)}
              title={entry.readable === false ? 'You likely do not have read access to this file' : undefined}
            >
              <span className="file-explorer-icon">{entry.is_dir ? '📁' : '📄'}</span>
              <span className="file-explorer-name">{entry.name}</span>
              {entry.permissions && (
                <code className="muted file-explorer-perms">
                  {entry.permissions}
                  {entry.readable === false && ' 🚫'}
                </code>
              )}
              {!entry.is_dir && typeof entry.size === 'number' && (
                <span className="muted file-explorer-size">{entry.size.toLocaleString()} B</span>
              )}
            </li>
          ))}
          {data.truncated && <li className="muted">List truncated — narrow it down by navigating deeper.</li>}
        </ul>
      )}
    </div>
  )
}
