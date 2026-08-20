"""Tests for the "docker" log source mode (docker-logs-backed, not a real
file). Runs against a real, disposable container via the actual `docker`
binary — this dev/CI host has Docker (it's used to build/run the app
itself), so this is genuine coverage rather than a mock. Skips cleanly if
docker isn't available or unreachable (e.g. no permission), matching the
project's existing approach for journalctl-backed tests.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid

import pytest

from logsonfire_agentcore.base import LogSourceSpec
from logsonfire_agentcore.docker import docker_container_from_path, make_docker_path
from logsonfire_agentcore.local import LocalFileProvider

def _docker_usable() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=5).returncode == 0
    except Exception:  # noqa: BLE001 - any failure means "can't use docker here"
        return False


pytestmark = pytest.mark.skipif(not _docker_usable(), reason="docker not available/reachable on this host")


@pytest.fixture
async def running_container():
    """A tiny container that logs a distinct line every 200ms, so both
    backfill (read_tail) and live tailing have real, predictable content
    to check without a fixed sleep racing the container's own startup."""
    name = f"logsonfire-test-{uuid.uuid4().hex[:12]}"
    subprocess.run(
        [
            "docker", "run", "-d", "--name", name, "busybox",
            "sh", "-c", "i=0; while true; do echo \"line $i\"; i=$((i+1)); sleep 0.2; done",
        ],
        check=True, capture_output=True,
    )
    try:
        # Give it a moment to actually produce a couple of lines before the
        # test starts asserting on backfill content.
        await asyncio.sleep(1.0)
        yield name
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def test_make_docker_path_and_round_trip():
    assert make_docker_path("my-app") == "docker://my-app"
    assert docker_container_from_path("docker://my-app") == "my-app"
    assert docker_container_from_path("/var/log/app.log") is None


async def test_resolve_sources_docker_mode_existing_container(running_container: str):
    provider = LocalFileProvider()
    spec = LogSourceSpec(mode="docker", path_or_pattern=running_container)
    files, truncated = await provider.resolve_sources(spec)
    assert not truncated
    assert len(files) == 1
    assert files[0].path == f"docker://{running_container}"
    assert files[0].warning is None


async def test_resolve_sources_docker_mode_missing_container_warns():
    provider = LocalFileProvider()
    spec = LogSourceSpec(mode="docker", path_or_pattern="logsonfire-does-not-exist-12345")
    files, truncated = await provider.resolve_sources(spec)
    assert not truncated
    assert len(files) == 1
    assert files[0].warning is not None
    assert "no container named" in files[0].warning.lower()


async def test_read_tail_docker_mode_returns_real_lines(running_container: str):
    provider = LocalFileProvider()
    lines = await provider.read_tail(f"docker://{running_container}", 5)
    assert 0 < len(lines) <= 5
    assert all("line " in line for line in lines)


async def test_tail_docker_mode_yields_live_lines(running_container: str):
    provider = LocalFileProvider()
    gen = provider.tail(f"docker://{running_container}")
    try:
        async with asyncio.timeout(10):
            line = await gen.__anext__()
        assert "line " in line
    finally:
        await gen.aclose()
