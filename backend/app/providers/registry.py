"""Picks the right LogProvider implementation for a Host."""
from __future__ import annotations

from app.models.host import Host
from app.providers.base import LogProvider
from app.providers.local import LocalFileProvider
from app.providers.ssh import SshFileProvider


def get_provider(host: Host) -> LogProvider:
    if host.connection_type == "local":
        return LocalFileProvider()
    if host.connection_type == "ssh":
        return SshFileProvider(host, host.credential)
    raise ValueError(f"unknown connection_type: {host.connection_type!r}")
