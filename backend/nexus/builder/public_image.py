"""Stage an exact public OCI image with enforced download bounds; loading is separate."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import tarfile
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from nexus.builder.public_download import PublicDownloader

REGISTRY = "https://registry-1.docker.io/v2/library/node"
TOKEN_URL = (
    "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/node:pull"
)
NODE_DIGEST: Literal["sha256:c4d5523090a817b7aa86d2111241fdd4f66d1e27782b44160e6aa63b357ecb2d"] = (
    "sha256:c4d5523090a817b7aa86d2111241fdd4f66d1e27782b44160e6aa63b357ecb2d"
)
OCI_MEDIA = "application/vnd.oci.image.manifest.v1+json"


class BlobDescriptor(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)
    media_type: str = Field(alias="mediaType", max_length=128)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size: int = Field(ge=0, le=629_145_600, strict=True)


class ImageManifest(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    schema_version: Literal[2] = Field(alias="schemaVersion")
    media_type: Literal["application/vnd.oci.image.manifest.v1+json"] = Field(alias="mediaType")
    config: BlobDescriptor
    layers: tuple[BlobDescriptor, ...] = Field(min_length=1, max_length=32)


class PublicImageReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    digest: Literal["sha256:c4d5523090a817b7aa86d2111241fdd4f66d1e27782b44160e6aa63b357ecb2d"]
    config_digest: str
    platform: Literal["linux/amd64"]
    downloaded_bytes: int
    layers: tuple[BlobDescriptor, ...]
    archive_sha256: str
    archive_bytes: int


def digest_integrity(digest: str) -> str:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("OCI descriptor digest is unsupported")
    return "sha256-" + base64.b64encode(bytes.fromhex(digest[7:])).decode()


async def public_token(client: httpx.AsyncClient) -> str:
    """Obtain only an anonymous public pull token; never persist or print it."""
    raw = bytearray()
    async with asyncio.timeout(30), client.stream("GET", TOKEN_URL) as response:
        response.raise_for_status()
        async for part in response.aiter_bytes(chunk_size=16384):
            raw.extend(part)
            if len(raw) > 65536:
                raise ValueError("Anonymous registry token response exceeds its bound")
    value = json.loads(raw)
    token = value.get("token")
    if not isinstance(token, str) or not 1 <= len(token) <= 16384:
        raise ValueError("Anonymous registry token is unavailable")
    return token


async def stage_public_node(root: Path, downloader: PublicDownloader) -> PublicImageReceipt:
    """Download only the selected platform manifest and its hash-bound blobs."""
    blobs = root / "blobs" / "sha256"
    await asyncio.to_thread(blobs.mkdir, mode=0o700, parents=True)
    authorization = "Bearer " + await public_token(downloader.client)
    initial_budget = downloader.budget.remaining_bytes
    manifest_path = blobs / NODE_DIGEST[7:]
    async with asyncio.timeout(600):
        await downloader.fetch(
            f"{REGISTRY}/manifests/{NODE_DIGEST}",
            manifest_path,
            digest_integrity(NODE_DIGEST),
            authorization=authorization,
            max_bytes=1_048_576,
        )
        raw = await asyncio.to_thread(manifest_path.read_bytes)
        if len(raw) > 1_048_576:
            raise ValueError("Public OCI manifest exceeds its bound")
        manifest = ImageManifest.model_validate_json(raw)
        await _download_blobs(blobs, manifest, downloader, authorization)
    config = json.loads(await asyncio.to_thread((blobs / manifest.config.digest[7:]).read_bytes))
    if config.get("os") != "linux" or config.get("architecture") != "amd64":
        raise ValueError("Public image actual platform differs from the approved packet")
    archive = root / "node-amd64.oci.tar"
    await asyncio.to_thread(_archive, root, archive, manifest, len(raw))
    return PublicImageReceipt(
        digest=NODE_DIGEST,
        config_digest=manifest.config.digest,
        platform="linux/amd64",
        downloaded_bytes=initial_budget - downloader.budget.remaining_bytes,
        layers=manifest.layers,
        archive_sha256=await asyncio.to_thread(file_sha256, archive),
        archive_bytes=(await asyncio.to_thread(archive.stat)).st_size,
    )


async def _download_blobs(
    blobs: Path,
    manifest: ImageManifest,
    downloader: PublicDownloader,
    authorization: str,
) -> None:
    if manifest.config.size > 1_048_576:
        raise ValueError("Public OCI config exceeds its bound")
    unique = {row.digest: row for row in (manifest.config, *manifest.layers)}
    if sum(row.size for row in unique.values()) > downloader.budget.remaining_bytes:
        raise ValueError("Public image declared bytes exceed the complete stage budget")
    for row in unique.values():
        await downloader.fetch(
            f"{REGISTRY}/blobs/{row.digest}",
            blobs / row.digest[7:],
            digest_integrity(row.digest),
            authorization=authorization,
            expected_size=row.size,
        )


def _archive(root: Path, archive: Path, manifest: ImageManifest, manifest_size: int) -> None:
    descriptor = {
        "mediaType": OCI_MEDIA,
        "digest": NODE_DIGEST,
        "size": manifest_size,
        "annotations": {"org.opencontainers.image.ref.name": "nexus-node-22.23.3-bookworm"},
        "platform": {"os": "linux", "architecture": "amd64"},
    }
    (root / "oci-layout").write_text('{"imageLayoutVersion":"1.0.0"}')
    (root / "index.json").write_text(json.dumps({"schemaVersion": 2, "manifests": [descriptor]}))
    names = ["oci-layout", "index.json", "blobs/sha256/" + NODE_DIGEST[7:]]
    names.extend("blobs/sha256/" + row.digest[7:] for row in (manifest.config, *manifest.layers))
    with archive.open("xb") as stream, tarfile.open(fileobj=stream, mode="w") as output:
        for name in sorted(set(names)):
            output.add(root / name, arcname=name, recursive=False)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while raw := stream.read(65536):
            digest.update(raw)
    return digest.hexdigest()
