"""Live "grep bar": runs the real `grep` binary against a TailSession's
in-memory buffer, so filtering/searching behaves exactly like real grep
(including -A/-B/-C context) — the point is partly to get users used to
actual grep syntax, not to reimplement a subset of it in Python.

Safety: the user-supplied expression is parsed into a whitelisted set of
flags plus one pattern via `shlex.split()` + explicit validation — it is
never passed through a shell. The pattern is always placed after a literal
`--` so it can never be misinterpreted as a flag. The buffer content is fed
to grep over stdin, so no path or filename is ever part of the command.
"""
from __future__ import annotations

import asyncio
import contextlib
import re
import shlex
from dataclasses import dataclass

GREP_TIMEOUT_SECONDS = 2.0
MAX_CONTEXT_LINES = 1000

# Flags that take no value.
_FLAGS_NO_ARG = {
    "-i", "--ignore-case",
    "-v", "--invert-match",
    "-c", "--count",
    "-n", "--line-number",
    "-w", "--word-regexp",
    "-x", "--line-regexp",
    "-F", "--fixed-strings",
    "-E", "--extended-regexp",
    "-o", "--only-matching",
}
# Flags that take a value (either attached "-A3" / "--after-context=3" or separate "-A 3").
_FLAGS_WITH_ARG = {
    "-A": "--after-context",
    "-B": "--before-context",
    "-C": "--context",
    "-m": "--max-count",
    "-e": "--regexp",
}
_CONTEXT_FLAGS = {"-A", "--after-context", "-B", "--before-context", "-C", "--context"}
_LONG_TO_SHORT = {long: short for short, long in _FLAGS_WITH_ARG.items()}

_OUTPUT_LINE_RE = re.compile(r"^(\d+)([:-])(.*)$", re.DOTALL)


class GrepExpressionError(ValueError):
    pass


@dataclass
class GrepResultLine:
    line_no: int | None
    text: str
    is_match: bool
    is_separator: bool = False


def parse_grep_expression(expression: str) -> tuple[list[tuple[str, str | None]], str]:
    expression = expression.strip()
    if not expression:
        raise GrepExpressionError("empty expression")

    try:
        tokens = shlex.split(expression)
    except ValueError as exc:  # unbalanced quotes etc.
        raise GrepExpressionError(f"could not parse expression: {exc}") from exc

    if tokens and tokens[0] == "grep":
        tokens = tokens[1:]
    if not tokens:
        raise GrepExpressionError("empty expression")

    flags: list[tuple[str, str | None]] = []
    pattern: str | None = None
    i = 0
    n = len(tokens)

    while i < n:
        tok = tokens[i]

        if not tok.startswith("-") or tok == "-":
            break  # first non-flag token: the pattern

        base, _, inline_value = tok.partition("=") if tok.startswith("--") else (tok, "", "")
        attached_value: str | None = None

        if not tok.startswith("--") and len(tok) > 2 and tok[:2] in _FLAGS_WITH_ARG:
            # attached short form, e.g. -A3
            base = tok[:2]
            attached_value = tok[2:]

        canonical = _LONG_TO_SHORT.get(base, base)

        if canonical in _FLAGS_WITH_ARG or base in _FLAGS_WITH_ARG:
            short = canonical if canonical in _FLAGS_WITH_ARG else base
            value = attached_value if attached_value is not None else (inline_value or None)
            if value is None:
                i += 1
                if i >= n:
                    raise GrepExpressionError(f"flag {tok} requires a value")
                value = tokens[i]
            if short != "-e" and not value.lstrip("-").isdigit():
                raise GrepExpressionError(f"flag {tok} requires a numeric value, got {value!r}")
            if short != "-e" and int(value) > MAX_CONTEXT_LINES:
                raise GrepExpressionError(f"flag {tok} value too large (max {MAX_CONTEXT_LINES})")
            if short == "-e":
                pattern = value
            flags.append((short, value))
            i += 1
            continue

        if base in _FLAGS_NO_ARG or tok in _FLAGS_NO_ARG:
            flags.append((tok if tok in _FLAGS_NO_ARG else base, None))
            i += 1
            continue

        # Combined short flags like "-in" -> only if every character is a
        # known no-arg short flag.
        if len(tok) > 2 and tok[1] != "-" and all(f"-{c}" in _FLAGS_NO_ARG for c in tok[1:]):
            flags.append((tok, None))
            i += 1
            continue

        raise GrepExpressionError(f"unsupported flag: {tok}")

    have_explicit_pattern = pattern is not None
    if not have_explicit_pattern:
        if i >= n:
            raise GrepExpressionError("no search pattern given")
        pattern = tokens[i]
        i += 1

    if i < n:
        raise GrepExpressionError("too many arguments (only one search pattern is supported)")

    return flags, pattern  # type: ignore[return-value]


async def run_grep(lines: list[str], expression: str, *, timeout: float = GREP_TIMEOUT_SECONDS) -> tuple[list[GrepResultLine], str | None]:
    try:
        flags, pattern = parse_grep_expression(expression)
    except GrepExpressionError as exc:
        return [], str(exc)

    argv: list[str] = ["grep", "-n", "--color=never"]
    for flag, value in flags:
        argv.append(flag)
        if value is not None:
            argv.append(value)
    argv.extend(["--", pattern])

    content = ("\n".join(lines) + "\n") if lines else ""

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return [], "grep binary not found on the server"

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(content.encode("utf-8")), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        with contextlib.suppress(ProcessLookupError):
            await proc.wait()
        return [], "grep timed out"

    # grep exit codes: 0 = matches found, 1 = no matches (not an error), >=2 = real error
    if proc.returncode not in (0, 1):
        message = stderr.decode("utf-8", "replace").strip() or f"grep exited with status {proc.returncode}"
        return [], message

    results: list[GrepResultLine] = []
    for raw_line in stdout.decode("utf-8", "replace").split("\n"):
        if raw_line == "":
            continue
        if raw_line == "--":
            results.append(GrepResultLine(line_no=None, text="--", is_match=False, is_separator=True))
            continue
        m = _OUTPUT_LINE_RE.match(raw_line)
        if not m:
            continue  # defensive: unexpected format, skip rather than misrender
        line_no, sep, text = m.groups()
        results.append(GrepResultLine(line_no=int(line_no), text=text, is_match=(sep == ":")))

    return results, None
