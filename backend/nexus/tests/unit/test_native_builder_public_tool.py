"""Verified public tool bytes do not permit traversal or link extraction."""

import base64
import hashlib
import io
import tarfile
from pathlib import Path

import pytest

from nexus.builder.public_tool_extract import extract_public_tool


def tar(kind: str) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        entry = tarfile.TarInfo("../outside" if kind == "path" else "package/bin/pnpm.cjs")
        if kind == "link":
            entry.type = tarfile.SYMTYPE
            entry.linkname = "/home/private"
        else:
            entry.size = 6
        archive.addfile(entry, None if kind == "link" else io.BytesIO(b"public"))
    return stream.getvalue()


@pytest.mark.parametrize("case", ["link", "path", "hash"])
def test_public_tool_unsafe_or_changed_bytes_deny_before_destination(
    tmp_path: Path, case: str
) -> None:
    raw = tar(case)
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode()
    if case == "hash":
        raw += b"changed"
    root = tmp_path / "tool"
    with pytest.raises(ValueError):
        extract_public_tool(raw, integrity, root)
    assert not root.exists() and not (tmp_path / "outside").exists()


def test_public_tool_ordinary_extraction_stays_private_and_hook_free(tmp_path: Path) -> None:
    raw = tar("ordinary")
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode()
    root = tmp_path / "tool"
    extract_public_tool(raw, integrity, root)
    assert (root / "package" / "bin" / "pnpm.cjs").read_bytes() == b"public"
    assert root.stat().st_mode & 0o777 == 0o700
