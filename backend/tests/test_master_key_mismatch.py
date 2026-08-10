"""A rotated/lost MASTER_KEY must fail cleanly (a clear SshAuthError message)
rather than as an unhandled `cryptography.exceptions.InvalidTag` bubbling up
as a bare 500 — this was an actual bug found via manual Docker testing.
"""
from __future__ import annotations

import pytest

from app.models.host import Host, HostCredential
from app.security import crypto as crypto_module
from app.ssh.connect import open_ssh_connection
from app.ssh.exceptions import SshAuthError


async def test_wrong_master_key_raises_clean_auth_error(monkeypatch):
    host = Host(
        id="h1",
        name="test",
        connection_type="ssh",
        hostname="example.invalid",
        port=22,
        ssh_username="root",
        auth_type="password",
    )
    # Encrypt with the current (test) key...
    credential = HostCredential(host_id="h1", encrypted_password=crypto_module.encrypt_str("supersecret"))

    # ...then simulate a MASTER_KEY rotation/loss by forcing a different key
    # to be used for decryption from this point on.
    crypto_module.reset_key_cache()
    monkeypatch.setenv("MASTER_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    from app.config import get_settings

    get_settings.cache_clear()
    crypto_module.reset_key_cache()

    with pytest.raises(SshAuthError, match="MASTER_KEY does not match"):
        await open_ssh_connection(host, credential)
