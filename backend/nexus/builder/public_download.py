"""Public HTTPS integrity downloads never inherit credentials or unrestricted redirects."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

import httpx


class _Hasher(Protocol):
    def update(self, raw: bytes) -> None: ...


@dataclass
class DownloadBudget:
    remaining_bytes: int
    timeout_seconds: int

    def __post_init__(self) -> None:
        if self.remaining_bytes <= 0 or self.timeout_seconds <= 0:
            raise ValueError("Public download limits must be positive")


def require_public_url(url: str, hosts: frozenset[str]) -> str:
    value = urlsplit(url)
    if (
        value.scheme != "https"
        or value.hostname not in hosts
        or value.username
        or value.password
        or value.port not in {None, 443}
    ):
        raise ValueError("Public download URL exceeds the exact HTTPS host policy")
    return value.hostname or ""


class PublicDownloader:
    def __init__(
        self,
        hosts: frozenset[str],
        budget: DownloadBudget,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.hosts, self.budget = hosts, budget
        self.client = httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            transport=transport,
            timeout=budget.timeout_seconds,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def fetch(
        self,
        url: str,
        destination: Path,
        integrity: str,
        *,
        authorization: str | None = None,
        expected_size: int | None = None,
        max_bytes: int | None = None,
    ) -> int:
        algorithm, _, expected = integrity.partition("-")
        if algorithm not in {"sha256", "sha512"} or not expected:
            raise ValueError("Public download integrity is unsupported")
        hasher = hashlib.new(algorithm)
        temporary = destination.with_name(destination.name + ".pending-" + uuid4().hex)
        origin = require_public_url(url, self.hosts)
        headers = {"Authorization": authorization} if authorization else {}
        try:
            async with asyncio.timeout(self.budget.timeout_seconds):
                for _ in range(4):
                    host = require_public_url(url, self.hosts)
                    if host != origin:
                        headers = {}
                    async with self.client.stream("GET", url, headers=headers) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            url = urljoin(url, response.headers.get("location", ""))
                            require_public_url(url, self.hosts)
                            continue
                        response.raise_for_status()
                        size = await self._stream(
                            response, temporary, hasher, expected_size, max_bytes
                        )
                        actual = base64.b64encode(hasher.digest()).decode()
                        if actual != expected:
                            raise ValueError("Public downloaded bytes fail the exact integrity pin")
                        await asyncio.to_thread(
                            os.link, temporary, destination, follow_symlinks=False
                        )
                        await asyncio.to_thread(temporary.unlink)
                        return size
                raise ValueError("Public download redirect count exceeds its bound")
        finally:
            await asyncio.to_thread(temporary.unlink, missing_ok=True)

    async def _stream(
        self,
        response: httpx.Response,
        temporary: Path,
        hasher: _Hasher,
        expected_size: int | None,
        max_bytes: int | None,
    ) -> int:
        if expected_size is not None and not 0 <= expected_size <= self.budget.remaining_bytes:
            raise ValueError("Public blob declared size exceeds its remaining budget")
        descriptor = await asyncio.to_thread(
            os.open, temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        size = 0
        with os.fdopen(descriptor, "wb") as stream:
            async for raw in response.aiter_bytes(chunk_size=65536):
                size += len(raw)
                if (
                    len(raw) > self.budget.remaining_bytes
                    or (expected_size is not None and size > expected_size)
                    or (max_bytes is not None and size > max_bytes)
                ):
                    raise ValueError("Public download exceeds its complete byte budget")
                self.budget.remaining_bytes -= len(raw)
                hasher.update(raw)
                await asyncio.to_thread(stream.write, raw)
            await asyncio.to_thread(_flush, stream)
        if expected_size is not None and size != expected_size:
            raise ValueError("Public blob actual size differs from its descriptor")
        return size


def _flush(stream: BinaryIO) -> None:
    stream.flush()
    os.fsync(stream.fileno())
