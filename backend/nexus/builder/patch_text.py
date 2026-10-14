"""Conservative bounded ordinary unified text patch parsing and exact context application."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from nexus.builder.paths import permitted_path
from nexus.builder.snapshot import source_path

MAX_PATCH_BYTES = 524288
MAX_PATCHED_FILE = 16_777_216
HEADER = re.compile(r"^diff --git a/([^\s]+) b/([^\s]+)\n$")
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?\n$")


@dataclass(frozen=True)
class TextHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class TextPatch:
    path: str
    hunks: tuple[TextHunk, ...]
    operation: Literal["modify", "create", "delete"] = "modify"


def parse_patch(
    raw: bytes, expected_sha256: str, allowed: tuple[str, ...]
) -> tuple[TextPatch, ...]:
    if not 0 < len(raw) <= MAX_PATCH_BYTES or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Builder patch bytes/hash exceed their boundary")
    text = raw.decode("utf-8")
    if "\x00" in text:
        raise ValueError("Builder binary patches are unsupported")
    lines = text.splitlines(keepends=True)
    result: list[TextPatch] = []
    offset = 0
    while offset < len(lines):
        match = HEADER.fullmatch(lines[offset])
        if match is None or match[1] != match[2] or not permitted_path(match[1], allowed):
            raise ValueError("Builder patch exceeds declared ordinary write paths")
        path = str(source_path(match[1]))
        offset += 1
        if offset >= len(lines):
            raise ValueError("Builder patch file headers are incomplete")
        operation: Literal["modify", "create", "delete"] = "modify"
        if lines[offset] in {"new file mode 100644\n", "deleted file mode 100644\n"}:
            operation = "create" if lines[offset].startswith("new ") else "delete"
            offset += 1
        if offset < len(lines) and lines[offset].startswith("index "):
            if not re.fullmatch(
                r"index [0-9a-f]{7,40}\.\.[0-9a-f]{7,40}(?: 100(?:644|755))?\n", lines[offset]
            ):
                raise ValueError("Builder patch mode or index is unsupported")
            offset += 1
        old = "/dev/null" if operation == "create" else "a/" + path
        new = "/dev/null" if operation == "delete" else "b/" + path
        if lines[offset : offset + 2] != [f"--- {old}\n", f"+++ {new}\n"]:
            raise ValueError("Builder patch text operation headers disagree")
        offset += 2
        hunks = []
        while offset < len(lines) and not lines[offset].startswith("diff --git "):
            hunk, offset = _parse_hunk(lines, offset)
            hunks.append(hunk)
        if not hunks or path in {row.path for row in result} or len(result) >= 32:
            raise ValueError("Builder patch has empty or duplicate file changes")
        result.append(TextPatch(path, tuple(hunks), operation))
    return tuple(result)


def _parse_hunk(lines: list[str], offset: int) -> tuple[TextHunk, int]:
    match = HUNK.fullmatch(lines[offset])
    if match is None:
        raise ValueError("Builder patch hunk syntax is unsupported")
    old_start, old_count, new_start, new_count = (
        int(match[1]),
        int(match[2] or 1),
        int(match[3]),
        int(match[4] or 1),
    )
    offset += 1
    body: list[str] = []
    while offset < len(lines) and not lines[offset].startswith(("@@ ", "diff --git ")):
        line = lines[offset]
        offset += 1
        if line == "\\ No newline at end of file\n" and body and body[-1].endswith("\n"):
            body[-1] = body[-1][:-1]
        elif line.startswith((" ", "+", "-")):
            body.append(line)
        else:
            raise ValueError("Builder patch contains an unsupported hunk entry")
    if (
        sum(line[0] != "+" for line in body) != old_count
        or sum(line[0] != "-" for line in body) != new_count
    ):
        raise ValueError("Builder patch hunk lengths disagree")
    return TextHunk(old_start, old_count, new_start, new_count, tuple(body)), offset


def apply_text(original: bytes, patch: TextPatch) -> bytes:
    lines = original.decode("utf-8").splitlines(keepends=True)
    output = []
    cursor = 0
    for hunk in patch.hunks:
        start = hunk.old_start - 1 if hunk.old_count else hunk.old_start
        if start < cursor or start > len(lines):
            raise ValueError("Builder patch old line position differs")
        output.extend(lines[cursor:start])
        cursor = start
        new_start = hunk.new_start - 1 if hunk.new_count else hunk.new_start
        if new_start != len(output):
            raise ValueError("Builder patch new line position differs")
        for line in hunk.lines:
            if line[0] != "+":
                if cursor >= len(lines) or lines[cursor] != line[1:]:
                    raise ValueError("Builder patch context differs from committed bytes")
                cursor += 1
            if line[0] != "-":
                output.append(line[1:])
    output.extend(lines[cursor:])
    raw = "".join(output).encode()
    if len(raw) > MAX_PATCHED_FILE:
        raise ValueError("Builder patched file exceeds its byte bound")
    return raw
