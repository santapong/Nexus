"""Bounded committed Git archives; no working-tree copy, checkout, fetch or tar extraction API."""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import re
import stat
import tarfile
from contextlib import suppress
from pathlib import Path, PurePosixPath

from nexus.builder.contracts import BuilderArtifact, RepositoryPin
from nexus.builder.paths import relative_path

MAX_ARCHIVE_BYTES = 33_554_432
MAX_SOURCE_BYTES = 16_777_216
MAX_SOURCE_FILES = 4096


def private_directory(descriptor: int) -> None:
    metadata = os.fstat(descriptor)
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ValueError("Builder job directory does not preserve private ownership/mode")


def require_git_read(arguments: tuple[str, ...], limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= MAX_ARCHIVE_BYTES:
        raise ValueError("Committed source read bound is invalid")
    archive = (
        len(arguments) == 3
        and arguments[:2] == ("archive", "--format=tar")
        and bool(re.fullmatch(r"[0-9a-f]{40}", arguments[2]))
    )
    revision = (
        arguments[:-1] in {("rev-parse",), ("rev-parse", "--verify")}
        and bool(re.fullmatch(r"[0-9a-f]{40}\^\{(?:commit|tree)\}", arguments[-1]))
        if arguments
        else False
    )
    if not (archive or revision):
        raise ValueError("Builder Git helper permits only exact committed archive/object reads")


async def git_bytes(repository: Path, *arguments: str, limit: int) -> bytes:
    """Internal trusted repository only; clear caller Git/credential/plugin environment."""
    require_git_read(arguments, limit)
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/git",
        "--no-replace-objects",
        "--no-optional-locks",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-C",
        str(repository),
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env={
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        },
    )
    assert process.stdout is not None
    result = bytearray()
    try:
        async with asyncio.timeout(15):
            while chunk := await process.stdout.read(min(65536, limit - len(result) + 1)):
                result.extend(chunk)
                if len(result) > limit:
                    raise ValueError("Committed builder source exceeds its byte bound")
            if await process.wait() != 0:
                raise ValueError("Committed builder source is unavailable")
        return bytes(result)
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        # Read PIPE to EOF before wait; an exited child can still leave unread buffered data.
        await asyncio.wait_for(process.communicate(), timeout=2)


async def committed_archive(repository: Path, pin: RepositoryPin) -> bytes:
    pin = RepositoryPin.model_validate_json(pin.model_dump_json())
    commit = await git_bytes(
        repository, "rev-parse", "--verify", f"{pin.commit}^{{commit}}", limit=64
    )
    tree = await git_bytes(repository, "rev-parse", f"{pin.commit}^{{tree}}", limit=64)
    if commit.decode().strip() != pin.commit or tree.decode().strip() != pin.tree:
        raise ValueError("Builder source commit/tree pin differs")
    raw = await git_bytes(
        repository, "archive", "--format=tar", pin.commit, limit=MAX_ARCHIVE_BYTES
    )
    if hashlib.sha256(raw).hexdigest() != pin.archive_sha256:
        raise ValueError("Builder source archive hash differs")
    return raw


def source_path(name: str) -> PurePosixPath:
    path = relative_path(name)
    if any(
        part in {"node_modules", ".codex", ".hermes", ".git-credentials"} for part in path.parts
    ):
        raise ValueError("Builder source includes a forbidden store")
    if path.name == ".env" or (
        path.name.startswith(".env.")
        and not path.name.endswith((".example", ".sample", ".template"))
    ):
        raise ValueError("Builder source includes a credential environment path")
    return path


def archive_members(archive: tarfile.TarFile) -> tuple[tarfile.TarInfo, ...]:
    values: list[tarfile.TarInfo] = []
    names: set[str] = set()
    total = 0
    for member in archive:
        if (
            len(values) >= MAX_SOURCE_FILES
            or not (member.isfile() or member.isdir())
            or member.sparse
        ):
            raise ValueError("Builder source archive has unsupported entries")
        name = member.name.rstrip("/") if member.isdir() else member.name
        source_path(name)
        if name in names or member.size < 0:
            raise ValueError("Builder source entries conflict")
        names.add(name)
        total += member.size
        if total > MAX_SOURCE_BYTES:
            raise ValueError("Builder source expands beyond its bound")
        values.append(member)
    return tuple(values)


def parent_descriptor(root: int, parts: tuple[str, ...]) -> int:
    parent = os.dup(root)
    try:
        for part in parts:
            with suppress(FileExistsError):
                os.mkdir(part, mode=0o700, dir_fd=parent)
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        return parent
    except BaseException:
        os.close(parent)
        raise


def write_member(
    archive: tarfile.TarFile, member: tarfile.TarInfo, root: int
) -> BuilderArtifact | None:
    path = source_path(member.name.rstrip("/") if member.isdir() else member.name)
    parent = parent_descriptor(root, path.parts if member.isdir() else path.parts[:-1])
    try:
        if member.isdir():
            return None
        stream = archive.extractfile(member)
        if stream is None:
            raise ValueError("Builder source file is unavailable")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptor = os.open(
            path.name, flags, 0o700 if member.mode & 0o111 else 0o600, dir_fd=parent
        )
        with stream, os.fdopen(descriptor, "wb") as destination:
            raw = stream.read(member.size + 1)
            if len(raw) != member.size:
                raise ValueError("Builder source file length differs")
            destination.write(raw)
        return BuilderArtifact(
            path=str(path), sha256=hashlib.sha256(raw).hexdigest(), byte_length=len(raw)
        )
    finally:
        os.close(parent)


def extract_source(
    raw: bytes, pin: RepositoryPin, destination: Path
) -> tuple[BuilderArtifact, ...]:
    """Only a fresh job directory is written; all archive entries validate before creation."""
    if len(raw) > MAX_ARCHIVE_BYTES or hashlib.sha256(raw).hexdigest() != pin.archive_sha256:
        raise ValueError("Builder source archive differs from its exact pin")
    if destination.exists() or destination.parent.resolve(strict=True) != destination.parent:
        raise ValueError("Builder destination must be fresh under an ordinary managed directory")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        members = archive_members(archive)
        destination.mkdir(mode=0o700)
        root = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            private_directory(root)
            values = tuple(
                value
                for member in members
                if (value := write_member(archive, member, root)) is not None
            )
            return tuple(sorted(values, key=lambda row: row.path))
        finally:
            os.close(root)
