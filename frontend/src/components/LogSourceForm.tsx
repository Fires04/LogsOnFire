import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Autocomplete, Button, Group, Loader, Paper, Select, Stack, Text, TextInput, Title } from '@mantine/core'
import { api } from '../lib/api'
import FileExplorer from './FileExplorer'
import Modal from './Modal'
import type {
  DockerContainersResponse,
  JournalUnitsResponse,
  LogSourceCreateInput,
  LogSourceMode,
  ResolveResponse,
} from '../types/models'

interface Props {
  agentId: string
  onCreate: (input: LogSourceCreateInput) => Promise<void>
}

const DEBOUNCE_MS = 400

const MODE_OPTIONS: { value: LogSourceMode; label: string }[] = [
  { value: 'exact_path', label: 'Exact path' },
  { value: 'glob', label: 'Glob pattern (*, ?, **)' },
  { value: 'regex', label: 'Regex over a directory' },
  { value: 'journal', label: 'systemd journal (journalctl)' },
  { value: 'docker', label: 'Docker container (docker logs)' },
]

// Neither journal nor docker names a filesystem path, so both are
// deterministic (no browse/pattern-match step) and get their own
// label/placeholder rather than falling into the path-shaped fields below.
const PATH_FIELD_LABEL: Record<LogSourceMode, string> = {
  exact_path: 'File path',
  glob: 'Glob pattern',
  regex: 'Regex (applied to the path relative to the base directory)',
  journal: 'Unit name (or * for the whole journal)',
  docker: 'Container name or ID',
}
const PATH_FIELD_PLACEHOLDER: Record<LogSourceMode, string> = {
  exact_path: '/var/log/nginx/access.log',
  glob: '/var/www/*/logs/*.log',
  regex: String.raw`logs/.*\.log$`,
  journal: 'nginx.service',
  docker: 'my-app-container',
}
// Modes with nothing on the agent's filesystem to browse to.
const NON_BROWSABLE_MODES: LogSourceMode[] = ['regex', 'journal', 'docker']

/** A sensible default Label so "Mode: journal, unit: nginx.service" doesn't
 * also require typing "Label: nginx journal" by hand — still just a
 * starting point, freely editable, and stops being touched the moment the
 * user edits Label themselves (see labelTouched below). */
function suggestLabel(mode: LogSourceMode, pathOrPattern: string): string {
  const trimmed = pathOrPattern.trim()
  if (!trimmed) return mode === 'journal' ? 'journal' : ''
  if (mode === 'journal') return trimmed === '*' ? 'journal' : `journal: ${trimmed}`
  if (mode === 'docker') return `docker: ${trimmed}`
  // exact_path / glob / regex — the last path segment, falling back to the
  // whole pattern if there isn't one (e.g. a bare filename, no slashes).
  const base = trimmed.replace(/\/+$/, '').split('/').filter(Boolean).pop()
  return base || trimmed
}

export default function LogSourceForm({ agentId, onCreate }: Props) {
  const [label, setLabel] = useState('')
  const [labelTouched, setLabelTouched] = useState(false)
  const [mode, setMode] = useState<LogSourceMode>('glob')
  const [pathOrPattern, setPathOrPattern] = useState('')
  const [regexBaseDir, setRegexBaseDir] = useState('')
  const [preview, setPreview] = useState<ResolveResponse | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [browsing, setBrowsing] = useState<'path' | 'regexBaseDir' | null>(null)
  const [journalUnits, setJournalUnits] = useState<string[]>([])
  const [dockerContainers, setDockerContainers] = useState<string[]>([])
  const [pickerLoading, setPickerLoading] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Auto-fill Label from the mode/pattern being entered, unless the user
  // has already typed something into Label themselves.
  useEffect(() => {
    if (!labelTouched) setLabel(suggestLabel(mode, pathOrPattern))
  }, [mode, pathOrPattern, labelTouched])

  // journal/docker path fields are pickers over what the agent actually
  // has, not free browsing — fetch the option list once per mode switch.
  // Best-effort: an empty/failed fetch just leaves the field as free text.
  useEffect(() => {
    if (mode !== 'journal' && mode !== 'docker') return
    let cancelled = false
    setPickerLoading(true)
    const req =
      mode === 'journal'
        ? api.get<JournalUnitsResponse>(`/api/agents/${agentId}/journal-units`).then((r) => {
            if (!cancelled) setJournalUnits(r.units)
          })
        : api.get<DockerContainersResponse>(`/api/agents/${agentId}/docker-containers`).then((r) => {
            if (!cancelled) setDockerContainers(r.containers)
          })
    req.catch(() => undefined).finally(() => {
      if (!cancelled) setPickerLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [agentId, mode])

  useEffect(() => {
    if (!pathOrPattern || (mode === 'regex' && !regexBaseDir)) {
      setPreview(null)
      return
    }
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      setPreviewing(true)
      try {
        const result = await api.post<ResolveResponse>(`/api/agents/${agentId}/log-sources/resolve-preview`, {
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
  }, [agentId, mode, pathOrPattern, regexBaseDir])

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
      setLabelTouched(false)
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
    <Paper component="form" onSubmit={onSubmit} withBorder p="md" radius="md">
      <Stack gap="sm">
        <Title order={4}>Add log source</Title>
        <TextInput
          label="Label"
          value={label}
          onChange={(e) => {
            setLabel(e.currentTarget.value)
            setLabelTouched(true)
          }}
          required
          placeholder="e.g. nginx access log"
        />
        <Select
          label="Mode"
          data={MODE_OPTIONS}
          value={mode}
          onChange={(v) => v && setMode(v as LogSourceMode)}
          allowDeselect={false}
        />

        {mode === 'regex' && (
          <Group align="flex-end" gap="xs">
            <TextInput
              label="Base directory to walk"
              value={regexBaseDir}
              onChange={(e) => setRegexBaseDir(e.currentTarget.value)}
              placeholder="/var/www"
              required
              style={{ flex: 1 }}
            />
            <Button variant="default" onClick={() => setBrowsing('regexBaseDir')}>
              Browse…
            </Button>
          </Group>
        )}

        <Group align="flex-end" gap="xs">
          {mode === 'journal' || mode === 'docker' ? (
            <Autocomplete
              style={{ flex: 1 }}
              label={PATH_FIELD_LABEL[mode]}
              description={pickerLoading ? undefined : 'Pick from what the agent found, or type your own'}
              value={pathOrPattern}
              onChange={setPathOrPattern}
              data={mode === 'journal' ? journalUnits : dockerContainers}
              placeholder={PATH_FIELD_PLACEHOLDER[mode]}
              rightSection={pickerLoading ? <Loader size="xs" /> : undefined}
              required
            />
          ) : (
            <TextInput
              style={{ flex: 1 }}
              label={PATH_FIELD_LABEL[mode]}
              value={pathOrPattern}
              onChange={(e) => setPathOrPattern(e.currentTarget.value)}
              placeholder={PATH_FIELD_PLACEHOLDER[mode]}
              required
            />
          )}
          {!NON_BROWSABLE_MODES.includes(mode) && (
            <Button variant="default" onClick={() => setBrowsing('path')}>
              Browse…
            </Button>
          )}
        </Group>

        {(previewing || preview) && (
          <Stack gap={2} pt="xs" style={{ borderTop: '1px dashed var(--mantine-color-default-border)' }}>
            {previewing && <Text c="dimmed" size="sm">Searching for matches…</Text>}
            {!previewing && preview?.error && <Text c="red" size="sm">{preview.error}</Text>}
            {!previewing && preview?.warning && <Text c="yellow" size="sm">⚠ {preview.warning}</Text>}
            {!previewing && preview && !preview.error && (
              <>
                <Text c="dimmed" size="sm">
                  {preview.files.length === 0
                    ? 'No matches yet.'
                    : `Found ${preview.files.length}${preview.truncated ? '+' : ''} file(s):`}
                </Text>
                {preview.files.slice(0, 8).map((f) => (
                  <Text key={f.path} component="code" fz="sm">
                    {f.path}
                    {typeof f.size === 'number' && <Text component="span" c="dimmed"> ({f.size} B)</Text>}
                  </Text>
                ))}
              </>
            )}
          </Stack>
        )}

        {error && <Text c="red" size="sm">{error}</Text>}
        <Button type="submit" loading={busy}>
          Add log source
        </Button>
      </Stack>

      {browsing && (
        <Modal onClose={() => setBrowsing(null)} wide>
          <FileExplorer
            agentId={agentId}
            onClose={() => setBrowsing(null)}
            onSelectFile={(path) => {
              setPathOrPattern(path)
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
    </Paper>
  )
}
