import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api } from '../lib/api'
import FileExplorer from './FileExplorer'
import Modal from './Modal'
import type { LogSourceCreateInput, LogSourceMode, ResolveResponse } from '../types/models'

interface Props {
  hostId: string
  onCreate: (input: LogSourceCreateInput) => Promise<void>
}

const DEBOUNCE_MS = 400

export default function LogSourceForm({ hostId, onCreate }: Props) {
  const [label, setLabel] = useState('')
  const [mode, setMode] = useState<LogSourceMode>('glob')
  const [pathOrPattern, setPathOrPattern] = useState('')
  const [regexBaseDir, setRegexBaseDir] = useState('')
  const [preview, setPreview] = useState<ResolveResponse | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [browsing, setBrowsing] = useState<'path' | 'regexBaseDir' | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!pathOrPattern || (mode === 'regex' && !regexBaseDir)) {
      setPreview(null)
      return
    }
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      setPreviewing(true)
      try {
        const result = await api.post<ResolveResponse>(`/api/hosts/${hostId}/log-sources/resolve-preview`, {
          label: label || 'preview',
          mode,
          path_or_pattern: pathOrPattern,
          regex_base_dir: mode === 'regex' ? regexBaseDir : undefined,
        })
        setPreview(result)
      } catch {
        setPreview(null)
      } finally {
        setPreviewing(false)
      }
    }, DEBOUNCE_MS)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hostId, mode, pathOrPattern, regexBaseDir])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await onCreate({
        label,
        mode,
        path_or_pattern: pathOrPattern,
        regex_base_dir: mode === 'regex' ? regexBaseDir : undefined,
      })
      setLabel('')
      setPathOrPattern('')
      setRegexBaseDir('')
      setPreview(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add log source')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={onSubmit}>
      <h2>Add log source</h2>
      <label>
        Label
        <input value={label} onChange={(e) => setLabel(e.target.value)} required placeholder="e.g. nginx access log" />
      </label>
      <label>
        Mode
        <select value={mode} onChange={(e) => setMode(e.target.value as LogSourceMode)}>
          <option value="exact_path">Exact path</option>
          <option value="glob">Glob pattern (*, ?, **)</option>
          <option value="regex">Regex over a directory</option>
          <option value="journal">systemd journal (journalctl)</option>
        </select>
      </label>

      {mode === 'regex' && (
        <label>
          Base directory to walk
          <div className="input-with-button">
            <input
              value={regexBaseDir}
              onChange={(e) => setRegexBaseDir(e.target.value)}
              placeholder="/var/www"
              required
            />
            <button type="button" className="secondary" onClick={() => setBrowsing('regexBaseDir')}>
              Browse…
            </button>
          </div>
        </label>
      )}

      <label>
        {mode === 'exact_path'
          ? 'File path'
          : mode === 'glob'
            ? 'Glob pattern'
            : mode === 'journal'
              ? 'Unit name (or * for the whole journal)'
              : 'Regex (applied to the path relative to the base directory)'}
        <div className="input-with-button">
          <input
            value={pathOrPattern}
            onChange={(e) => setPathOrPattern(e.target.value)}
            placeholder={
              mode === 'glob'
                ? '/var/www/*/logs/*.log'
                : mode === 'exact_path'
                  ? '/var/log/nginx/access.log'
                  : mode === 'journal'
                    ? 'nginx.service'
                    : String.raw`logs/.*\.log$`
            }
            required
          />
          {mode !== 'regex' && mode !== 'journal' && (
            <button type="button" className="secondary" onClick={() => setBrowsing('path')}>
              Browse…
            </button>
          )}
        </div>
      </label>

      <div className="preview-box">
        {previewing && <p className="muted">Searching for matches…</p>}
        {!previewing && preview?.error && <p className="error">{preview.error}</p>}
        {!previewing && preview?.warning && <p className="warning">⚠ {preview.warning}</p>}
        {!previewing && preview && !preview.error && (
          <>
            <p className="muted">
              {preview.files.length === 0
                ? 'No matches yet.'
                : `Found ${preview.files.length}${preview.truncated ? '+' : ''} file(s):`}
            </p>
            <ul className="preview-list">
              {preview.files.slice(0, 8).map((f) => (
                <li key={f.path}>
                  <code>{f.path}</code>
                  {typeof f.size === 'number' && <span className="muted"> ({f.size} B)</span>}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={busy}>
        {busy ? 'Adding…' : 'Add log source'}
      </button>

      {browsing && (
        <Modal onClose={() => setBrowsing(null)} wide>
          <FileExplorer
            hostId={hostId}
            onClose={() => setBrowsing(null)}
            onSelectFile={(path) => {
              setPathOrPattern(path)
              setLabel((prev) => (prev.trim() ? prev : path.split('/').filter(Boolean).pop() ?? path))
              setBrowsing(null)
            }}
            onSelectDirectory={
              browsing === 'regexBaseDir'
                ? (path) => {
                    setRegexBaseDir(path)
                    setBrowsing(null)
                  }
                : mode === 'glob'
                  ? (path) => {
                      setPathOrPattern(`${path}/*`)
                      setBrowsing(null)
                    }
                  : undefined
            }
          />
        </Modal>
      )}
    </form>
  )
}
