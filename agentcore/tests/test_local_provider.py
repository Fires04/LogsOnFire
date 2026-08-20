from __future__ import annotations

import os
from pathlib import Path

import pytest

from logsonfire_agentcore.base import LogSourceSpec
from logsonfire_agentcore.local import LocalFileProvider


async def test_exact_path_resolves_when_file_exists(tmp_path: Path):
    f = tmp_path / "app.log"
    f.write_text("line1\nline2\n")
    provider = LocalFileProvider()
    files, truncated = await provider.resolve_sources(LogSourceSpec(mode="exact_path", path_or_pattern=str(f)))
    assert not truncated
    assert len(files) == 1
    assert files[0].path == str(f)
    assert files[0].size == f.stat().st_size


async def test_exact_path_missing_file_returns_empty(tmp_path: Path):
    provider = LocalFileProvider()
    files, truncated = await provider.resolve_sources(
        LogSourceSpec(mode="exact_path", path_or_pattern=str(tmp_path / "nope.log"))
    )
    assert files == []
    assert not truncated


async def test_glob_matches_nested_pattern_like_var_www(tmp_path: Path):
    # Mirrors the user's original example: /var/www/*/logs/*.log
    (tmp_path / "site-a" / "logs").mkdir(parents=True)
    (tmp_path / "site-b" / "logs").mkdir(parents=True)
    (tmp_path / "site-a" / "logs" / "app.log").write_text("a\n")
    (tmp_path / "site-b" / "logs" / "app.log").write_text("b\n")
    (tmp_path / "site-b" / "logs" / "other.txt").write_text("ignored\n")

    provider = LocalFileProvider()
    pattern = str(tmp_path / "*" / "logs" / "*.log")
    files, truncated = await provider.resolve_sources(LogSourceSpec(mode="glob", path_or_pattern=pattern))
    assert not truncated
    paths = sorted(f.path for f in files)
    assert paths == sorted(
        [str(tmp_path / "site-a" / "logs" / "app.log"), str(tmp_path / "site-b" / "logs" / "app.log")]
    )


async def test_glob_pattern_with_shell_metacharacters_in_filename_is_treated_literally(tmp_path: Path):
    """A filename containing shell metacharacters must never be executed —
    Python's glob module never invokes a shell, so this just has to match
    (or not match) as a literal filename like any other.
    """
    tricky = tmp_path / "app;touch_pwned.log"
    tricky.write_text("hello\n")

    provider = LocalFileProvider()
    files, truncated = await provider.resolve_sources(
        LogSourceSpec(mode="glob", path_or_pattern=str(tmp_path / "*.log"))
    )
    assert not truncated
    assert [f.path for f in files] == [str(tricky)]
    assert not (tmp_path / "pwned").exists()


async def test_regex_mode_filters_by_relative_path(tmp_path: Path):
    (tmp_path / "site-a" / "logs").mkdir(parents=True)
    (tmp_path / "site-a" / "logs" / "app.log").write_text("a\n")
    (tmp_path / "site-a" / "logs" / "debug.log").write_text("d\n")
    (tmp_path / "site-a" / "cache.tmp").write_text("x\n")

    provider = LocalFileProvider()
    spec = LogSourceSpec(mode="regex", path_or_pattern=r"logs/.*\.log$", regex_base_dir=str(tmp_path))
    files, truncated = await provider.resolve_sources(spec)
    assert not truncated
    paths = sorted(f.path for f in files)
    assert paths == sorted(
        [str(tmp_path / "site-a" / "logs" / "app.log"), str(tmp_path / "site-a" / "logs" / "debug.log")]
    )


async def test_regex_mode_invalid_pattern_raises_value_error(tmp_path: Path):
    provider = LocalFileProvider()
    spec = LogSourceSpec(mode="regex", path_or_pattern="[", regex_base_dir=str(tmp_path))
    with pytest.raises(ValueError):
        await provider.resolve_sources(spec)


async def test_read_tail_returns_last_n_lines(tmp_path: Path):
    f = tmp_path / "big.log"
    f.write_text("".join(f"line{i}\n" for i in range(1000)))
    provider = LocalFileProvider()
    lines = await provider.read_tail(str(f), 5)
    assert lines == [f"line{i}" for i in range(995, 1000)]


async def test_read_tail_handles_file_smaller_than_requested(tmp_path: Path):
    f = tmp_path / "small.log"
    f.write_text("only\ntwo\n")
    provider = LocalFileProvider()
    lines = await provider.read_tail(str(f), 100)
    assert lines == ["only", "two"]


async def test_list_directory_sorts_dirs_first(tmp_path: Path):
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


async def test_list_directory_reports_permissions_and_readability(tmp_path: Path):
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

        # root (uid 0, e.g. inside a test container) can read anything
        # regardless of mode bits, so only assert the strict case off-root.
        if os.geteuid() != 0:
            assert by_name["unreadable.log"].readable is False
    finally:
        unreadable.chmod(0o644)  # restore so tmp_path cleanup can remove it


async def test_default_browse_path_is_a_real_directory():
    provider = LocalFileProvider()
    path = await provider.default_browse_path()
    assert os.path.isdir(path)
