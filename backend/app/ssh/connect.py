"""Establishing a single asyncssh connection to a Host, including decrypting
its stored credential and trust-on-first-use host key pinning.

This module intentionally does NOT do any pooling/caching — see
app/ssh/pool.py (added in a later phase) for connection reuse across
concurrent tails. Keeping raw connection setup here lets both the pool and
one-off callers (e.g. the "test connection" button) share the exact same,
carefully-reviewed auth/host-key logic.
"""
from __future__ import annotations

import asyncio
import logging

import asyncssh
from cryptography.exceptions import InvalidTag

from app.config import get_settings
from app.models.host import Host, HostCredential
from app.security.crypto import decrypt_str
from app.ssh.exceptions import SshAuthError, SshConnectError, SshHostKeyError

logger = logging.getLogger("logsonfire.ssh")


def _decrypt_credential(data: bytes, field_name: str) -> str:
    """Decrypt a stored credential field, turning a wrong/rotated MASTER_KEY
    into a clean, actionable error instead of an unhandled crypto exception
    bubbling up as a raw 500.
    """
    try:
        return decrypt_str(data)
    except InvalidTag as exc:
        raise SshAuthError(
            f"could not decrypt stored {field_name} — MASTER_KEY does not match the one used to "
            "encrypt it (lost/rotated key, or wrong key configured). The credential must be "
            "re-entered; see README for details."
        ) from exc


def host_key_line(hostname: str, port: int, key: asyncssh.SSHKey) -> str:
    """Render a server host key as a single OpenSSH known_hosts-format line."""
    pattern = hostname if port == 22 else f"[{hostname}]:{port}"
    algo, b64key = key.export_public_key().decode().split()[:2]
    return f"{pattern} {algo} {b64key}"


def key_fingerprint(key: asyncssh.SSHKey) -> str:
    return key.get_fingerprint("sha256")


async def open_ssh_connection(
    host: Host, credential: HostCredential | None, *, verify_known_host: bool = True
) -> asyncssh.SSHClientConnection:
    """Open a fresh SSH connection to `host` using its stored credential.

    If `host.known_host_key` is already set, the server's host key is
    strictly verified against it (raises SshHostKeyError on mismatch). If it
    is not set yet, the connection proceeds without verification (first
    trust-on-first-use connection) — the caller is responsible for capturing
    and persisting the resulting host key via `host_key_line()`.
    """
    if host.connection_type != "ssh":
        raise ValueError("open_ssh_connection() called for a non-ssh host")

    settings = get_settings()
    known_hosts = None
    if verify_known_host and host.known_host_key:
        known_hosts = host.known_host_key.encode()

    connect_kwargs: dict = dict(
        host=host.hostname,
        port=host.port,
        username=host.ssh_username,
        known_hosts=known_hosts,
        connect_timeout=settings.ssh_connect_timeout_seconds,
    )

    if host.auth_type == "password":
        if not credential or not credential.encrypted_password:
            raise SshAuthError("host has no stored password credential")
        connect_kwargs["password"] = _decrypt_credential(credential.encrypted_password, "password")
        connect_kwargs["preferred_auth"] = ["password"]
    elif host.auth_type == "private_key":
        if not credential or not credential.encrypted_private_key:
            raise SshAuthError("host has no stored private key credential")
        passphrase = (
            _decrypt_credential(credential.encrypted_private_key_passphrase, "private key passphrase")
            if credential.encrypted_private_key_passphrase
            else None
        )
        try:
            private_key = asyncssh.import_private_key(
                _decrypt_credential(credential.encrypted_private_key, "private key"), passphrase=passphrase
            )
        except (asyncssh.KeyImportError, asyncssh.KeyEncryptionError) as exc:
            # KeyImportError: malformed key / wrong or missing passphrase.
            # KeyEncryptionError: e.g. the `bcrypt` package (needed to decrypt
            # modern bcrypt-KDF encrypted OpenSSH keys) isn't installed —
            # both are user/deployment-fixable, never an unhandled 500.
            raise SshAuthError(f"stored private key could not be parsed: {exc}") from exc
        connect_kwargs["client_keys"] = [private_key]
        connect_kwargs["preferred_auth"] = ["publickey"]
    else:
        raise SshAuthError(f"unsupported auth_type: {host.auth_type!r}")

    try:
        return await asyncssh.connect(**connect_kwargs)
    except asyncssh.HostKeyNotVerifiable as exc:
        raise SshHostKeyError(
            f"host key for {host.hostname}:{host.port} does not match the pinned key — "
            "possible server change or MITM. Use 'reset trust' if this change is expected."
        ) from exc
    except asyncssh.PermissionDenied as exc:
        raise SshAuthError(f"authentication failed: {exc}") from exc
    except (asyncssh.ConnectionLost, asyncssh.DisconnectError, OSError, asyncio.TimeoutError) as exc:
        raise SshConnectError(f"could not connect to {host.hostname}:{host.port}: {exc}") from exc
