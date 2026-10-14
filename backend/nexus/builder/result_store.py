"""Private immutable known-output envelopes are saved before the M1 receipt."""

from __future__ import annotations

import asyncio
import base64
import fcntl
import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.snapshot import private_directory
from nexus.company.management.canonical import canonical_sha256


class BuilderResultStore:
    def __init__(self, root: Path) -> None:
        root.mkdir(mode=0o700, parents=False, exist_ok=True)
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            private_directory(descriptor)
        finally:
            os.close(descriptor)
        self.root = root

    def path(self, spec: BuilderExecutionSpec) -> Path:
        return self.root / f"{spec.job.company_id.hex}-{spec.job.action_id.hex}.json"

    async def load(self, spec: BuilderExecutionSpec) -> BuilderRunResult | None:
        def read() -> BuilderRunResult | None:
            path = self.path(spec)
            if not path.exists():
                return None
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                raw = stream.read(100_663_297)
            if len(raw) > 100_663_296:
                raise ValueError("Builder saved result exceeds its bound")
            value = json.loads(raw)
            payload = value["payload"]
            if hashlib.sha256(payload.encode()).hexdigest() != value["sha256"]:
                raise ValueError("Builder saved result checksum differs")
            result = BuilderRunResult.model_validate_json(payload)
            if result.spec != spec:
                raise ValueError("Builder known output binds another exact job")
            for row in (*result.artifacts, *result.logs):
                content = base64.b64decode(row.content_base64, validate=True)
                if (
                    len(content) != row.metadata.byte_length
                    or hashlib.sha256(content).hexdigest() != row.metadata.sha256
                ):
                    raise ValueError("Builder saved artifact bytes differ")
            return result

        return await asyncio.to_thread(read)

    async def save(self, result: BuilderRunResult) -> None:
        payload = result.model_dump_json()
        raw = json.dumps(
            {"sha256": hashlib.sha256(payload.encode()).hexdigest(), "payload": payload}
        ).encode()
        if len(raw) > 100_663_296:
            raise ValueError("Builder result envelope exceeds its bound")

        def write() -> None:
            path = self.path(result.spec)
            if path.exists():
                if path.read_bytes() != raw:
                    raise ValueError("Builder known output is immutable")
                return
            temporary = path.with_suffix(".pending")
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            # A link creates the final immutable name without replacing an existing result.
            os.link(temporary, path, follow_symlinks=False)
            temporary.unlink()
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)

        await asyncio.to_thread(write)

    @contextmanager
    def slot(self) -> Iterator[None]:
        descriptor = os.open(self.root / "slot.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(descriptor)

    @staticmethod
    def digest(result: BuilderRunResult) -> str:
        return canonical_sha256(result)
