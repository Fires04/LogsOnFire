import { useState, type FormEvent } from 'react'
import type { AuthType, ConnectionType, Host, HostCreateInput, HostUpdateInput } from '../types/models'

interface Props {
  /** When set, the form edits this host instead of creating a new one. */
  editingHost?: Host
  onSubmit: (input: HostCreateInput | HostUpdateInput) => Promise<void>
  onCancel?: () => void
}

export default function HostForm({ editingHost, onSubmit, onCancel }: Props) {
  const isEdit = !!editingHost
  const [connectionType, setConnectionType] = useState<ConnectionType>(editingHost?.connection_type ?? 'ssh')
  const [name, setName] = useState(editingHost?.name ?? '')
  const [hostname, setHostname] = useState(editingHost?.hostname ?? '')
  const [port, setPort] = useState(editingHost?.port ?? 22)
  const [sshUsername, setSshUsername] = useState(editingHost?.ssh_username ?? '')
  const [authType, setAuthType] = useState<AuthType>(editingHost?.auth_type ?? 'password')
  const [password, setPassword] = useState('')
  const [privateKey, setPrivateKey] = useState('')
  const [passphrase, setPassphrase] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      if (isEdit) {
        await onSubmit({
          name,
          ...(connectionType === 'ssh'
            ? {
                hostname,
                port,
                ssh_username: sshUsername,
                auth_type: authType,
                password: authType === 'password' && password ? password : undefined,
                private_key: authType === 'private_key' && privateKey ? privateKey : undefined,
                private_key_passphrase: authType === 'private_key' && passphrase ? passphrase : undefined,
              }
            : {}),
        })
      } else {
        await onSubmit({
          name,
          connection_type: connectionType,
          ...(connectionType === 'ssh'
            ? {
                hostname,
                port,
                ssh_username: sshUsername,
                auth_type: authType,
                password: authType === 'password' ? password : undefined,
                private_key: authType === 'private_key' ? privateKey : undefined,
                private_key_passphrase: authType === 'private_key' ? passphrase || undefined : undefined,
              }
            : {}),
        })
        setName('')
        setHostname('')
        setSshUsername('')
        setPassword('')
        setPrivateKey('')
        setPassphrase('')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to ${isEdit ? 'save host' : 'add host'}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h2>{isEdit ? `Edit ${editingHost!.name}` : 'Add host'}</h2>
      <label>
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </label>
      <label>
        Connection type
        <select
          value={connectionType}
          onChange={(e) => setConnectionType(e.target.value as ConnectionType)}
          disabled={isEdit}
          title={isEdit ? "Connection type can't be changed after creation" : undefined}
        >
          <option value="ssh">SSH (remote server)</option>
          <option value="local">Local (this app's filesystem)</option>
        </select>
      </label>

      {connectionType === 'ssh' && (
        <>
          <div className="form-row">
            <label>
              Hostname / IP
              <input value={hostname} onChange={(e) => setHostname(e.target.value)} required />
            </label>
            <label className="port-field">
              Port
              <input type="number" value={port} onChange={(e) => setPort(Number(e.target.value))} required />
            </label>
          </div>
          <label>
            SSH user
            <input value={sshUsername} onChange={(e) => setSshUsername(e.target.value)} required />
          </label>
          <label>
            Authentication
            <select value={authType} onChange={(e) => setAuthType(e.target.value as AuthType)}>
              <option value="password">Password</option>
              <option value="private_key">SSH key</option>
            </select>
          </label>
          {authType === 'password' ? (
            <label>
              Password {isEdit && <span className="muted">(leave blank to keep the current one)</span>}
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required={!isEdit}
                placeholder={isEdit ? '••••••••' : undefined}
              />
            </label>
          ) : (
            <>
              <label>
                Private key (file contents){' '}
                {isEdit && <span className="muted">(leave blank to keep the current one)</span>}
                <textarea
                  rows={5}
                  value={privateKey}
                  onChange={(e) => setPrivateKey(e.target.value)}
                  placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                  required={!isEdit}
                />
              </label>
              <label>
                Passphrase (optional){' '}
                {isEdit && <span className="muted">(leave blank to keep the current one)</span>}
                <input type="password" value={passphrase} onChange={(e) => setPassphrase(e.target.value)} />
              </label>
            </>
          )}
        </>
      )}

      {error && <p className="error">{error}</p>}
      <div className="form-actions">
        <button type="submit" disabled={busy}>
          {busy ? 'Saving…' : isEdit ? 'Save changes' : 'Add host'}
        </button>
        {onCancel && (
          <button type="button" className="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
        )}
      </div>
    </form>
  )
}
