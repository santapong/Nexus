"""Controlled responses reproduce integrity/redirect/overflow/cleanup and credential isolation."""

import asyncio
import base64
import hashlib
from pathlib import Path

import httpx
import pytest

from nexus.builder.public_download import DownloadBudget, PublicDownloader


def integrity(raw: bytes) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode()


async def test_exact_public_download_hash_and_no_inherited_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "https://private-credential@example.invalid")
    seen = []

    def response(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        return httpx.Response(200, content=b"exact public tool")

    downloader = PublicDownloader(
        frozenset({"registry.npmjs.org"}),
        DownloadBudget(32, 2),
        transport=httpx.MockTransport(response),
    )
    try:
        size = await downloader.fetch(
            "https://registry.npmjs.org/tool.tgz",
            tmp_path / "tool",
            integrity(b"exact public tool"),
        )
        assert (
            size == 17
            and (tmp_path / "tool").read_bytes() == b"exact public tool"
            and seen == [None]
        )
    finally:
        await downloader.close()


@pytest.mark.parametrize("case", ["hash", "overflow", "redirect"])
async def test_failed_download_removes_partial_and_never_follows_unapproved_host(
    tmp_path: Path, case: str
) -> None:
    seen = []

    def response(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if case == "redirect":
            return httpx.Response(
                302, headers={"location": "https://private.example.invalid/token"}
            )
        return httpx.Response(200, content=b"payload")

    downloader = PublicDownloader(
        frozenset({"registry.npmjs.org"}),
        DownloadBudget(2 if case == "overflow" else 32, 2),
        transport=httpx.MockTransport(response),
    )
    try:
        with pytest.raises(ValueError):
            await downloader.fetch(
                "https://registry.npmjs.org/tool.tgz",
                tmp_path / "tool",
                integrity(b"wrong" if case == "hash" else b"payload"),
            )
        assert not (tmp_path / "tool").exists() and not tuple(tmp_path.glob("tool.pending-*"))
        assert len(seen) == 1
    finally:
        await downloader.close()


async def test_declared_blob_size_and_existing_result_are_preserved(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"payload"))
    downloader = PublicDownloader(
        frozenset({"registry.npmjs.org"}), DownloadBudget(32, 2), transport=transport
    )
    destination = tmp_path / "tool"
    destination.write_bytes(b"immutable original")
    try:
        with pytest.raises(ValueError, match="size differs"):
            await downloader.fetch(
                "https://registry.npmjs.org/tool",
                destination,
                integrity(b"payload"),
                expected_size=8,
            )
        with pytest.raises(FileExistsError):
            await downloader.fetch(
                "https://registry.npmjs.org/tool",
                destination,
                integrity(b"payload"),
                expected_size=7,
            )
        assert destination.read_bytes() == b"immutable original"
        assert not tuple(tmp_path.glob("tool.pending-*"))
    finally:
        await downloader.close()


class SlowBody(httpx.AsyncByteStream):
    async def __aiter__(self):  # type: ignore[no-untyped-def]
        yield b"partial"
        await asyncio.sleep(2)
        yield b"late"


async def test_timeout_removes_only_its_partial_file(tmp_path: Path) -> None:
    existing = tmp_path / "tool.pending-existing"
    existing.write_bytes(b"another immutable stage")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=SlowBody()))
    downloader = PublicDownloader(
        frozenset({"registry.npmjs.org"}), DownloadBudget(32, 1), transport=transport
    )
    try:
        with pytest.raises(TimeoutError):
            await downloader.fetch(
                "https://registry.npmjs.org/tool", tmp_path / "tool", integrity(b"partiallate")
            )
        assert tuple(tmp_path.glob("tool.pending-*")) == (existing,)
        assert existing.read_bytes() == b"another immutable stage"
        assert not (tmp_path / "tool").exists()
    finally:
        await downloader.close()


async def test_allowed_cdn_redirect_strips_registry_bearer(tmp_path: Path) -> None:
    seen = []

    def response(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers.get("authorization")))
        return (
            httpx.Response(302, headers={"location": "https://cdn.example/tool"})
            if request.url.host == "registry.example"
            else httpx.Response(200, content=b"public")
        )

    downloader = PublicDownloader(
        frozenset({"registry.example", "cdn.example"}),
        DownloadBudget(32, 2),
        transport=httpx.MockTransport(response),
    )
    try:
        await downloader.fetch(
            "https://registry.example/tool",
            tmp_path / "tool",
            integrity(b"public"),
            authorization="Bearer public-anonymous-read-token",
        )
        assert seen == [
            ("registry.example", "Bearer public-anonymous-read-token"),
            ("cdn.example", None),
        ]
    finally:
        await downloader.close()
