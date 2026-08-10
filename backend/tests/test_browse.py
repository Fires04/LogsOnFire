from __future__ import annotations

import os
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.providers.local import LocalFileProvider


async def test_local_provider_list_directory_sorts_dirs_first(tmp_path: Path):
    (tmp_path / "zzz-dir").mkdir()
    (tmp_path / "aaa-dir").mkdir()
    (tmp_path / "aaa-file.log").write_text("x")
    (tmp_path / "zzz-file.log").write_text("x")

    provider = LocalFileProvider()
    entries, truncated = await provider.list_directory(str(tmp_path))
    assert not truncated
    names = [e.name for e in entries]
    assert names == ["aaa-dir", "zzz-dir", "aaa-file.log", "zzz-file.log"]
    assert all(e.is_dir for e in entries[:2])
    assert all(not e.is_dir for e in entries[2:])


async def test_local_provider_default_browse_path_is_root():
    provider = LocalFileProvider()
    assert await provider.default_browse_path() == "/"


async def test_local_provider_list_directory_reports_permissions_and_readability(tmp_path: Path):
    readable = tmp_path / "readable.log"
    readable.write_text("x")
    unreadable = tmp_path / "unreadable.log"
    unreadable.write_text("x")
    unreadable.chmod(0o000)
    try:
        provider = LocalFileProvider()
        entries, _ = await provider.list_directory(str(tmp_path))
        by_name = {e.name: e for e in entries}

        assert by_name["readable.log"].permissions is not None
        assert by_name["readable.log"].permissions.startswith("-")
        assert by_name["readable.log"].readable is True

        # root (uid 0, e.g. inside the test container) can read anything
        # regardless of mode bits, so only assert the strict case off-root.
        if os.geteuid() != 0:
            assert by_name["unreadable.log"].readable is False
    finally:
        unreadable.chmod(0o644)  # restore so tmp_path cleanup can remove it


async def test_browse_endpoint_lists_local_directory(auth_client: AsyncClient, tmp_path: Path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "app.log").write_text("hello\n")

    host = await auth_client.post("/api/hosts", json={"name": "local", "connection_type": "local"})
    host_id = host.json()["id"]

    resp = await auth_client.get(f"/api/hosts/{host_id}/browse", params={"path": str(tmp_path)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["error"] is None
    names = {e["name"] for e in body["entries"]}
    assert {"sub", "app.log"} <= names
    sub_entry = next(e for e in body["entries"] if e["name"] == "sub")
    assert sub_entry["is_dir"] is True
    file_entry = next(e for e in body["entries"] if e["name"] == "app.log")
    assert file_entry["is_dir"] is False
    assert file_entry["size"] == 6


async def test_browse_endpoint_reports_missing_directory_as_clean_error(auth_client: AsyncClient, tmp_path: Path):
    host = await auth_client.post("/api/hosts", json={"name": "local", "connection_type": "local"})
    host_id = host.json()["id"]

    resp = await auth_client.get(f"/api/hosts/{host_id}/browse", params={"path": str(tmp_path / "nope")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is not None
    assert body["entries"] == []


async def test_browse_endpoint_reports_parent_even_when_listing_fails(auth_client: AsyncClient, tmp_path: Path):
    """Regression: a directory that fails to list (e.g. permission denied)
    used to come back with parent=None, disabling the "Up" button exactly
    when the user needs it most to back out of it."""
    if os.geteuid() == 0:
        pytest.skip("running as root - permission bits don't block access, can't exercise the error path")

    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o000)
    try:
        host = await auth_client.post("/api/hosts", json={"name": "local", "connection_type": "local"})
        host_id = host.json()["id"]

        resp = await auth_client.get(f"/api/hosts/{host_id}/browse", params={"path": str(blocked)})
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"] is not None
        assert body["parent"] == str(tmp_path)
    finally:
        blocked.chmod(0o755)


async def test_browse_endpoint_defaults_to_root_when_no_path_given(auth_client: AsyncClient):
    host = await auth_client.post("/api/hosts", json={"name": "local", "connection_type": "local"})
    host_id = host.json()["id"]

    resp = await auth_client.get(f"/api/hosts/{host_id}/browse")
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == "/"
    assert body["parent"] is None
