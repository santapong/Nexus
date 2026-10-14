"""Only a controlled integrity downloader contacts public registry; pnpm stays offline."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from pydantic import Field

from nexus.builder.contracts import BuilderValue
from nexus.builder.public_download import DownloadBudget, PublicDownloader
from nexus.builder.public_package_contracts import PublicPackageManifest
from nexus.builder.snapshot import private_directory


class PublicPackageReceipt(BuilderValue):
    manifest: PublicPackageManifest
    downloaded_bytes: int = Field(ge=0, le=536_870_912, strict=True)
    downloaded_packages: int = Field(ge=0, le=1024, strict=True)


async def download_packages(
    root: Path, manifest: PublicPackageManifest, *, downloader: PublicDownloader | None = None
) -> PublicPackageReceipt:
    await asyncio.to_thread(_prepare, root)
    owned = downloader is None
    client = downloader or PublicDownloader(
        frozenset({"registry.npmjs.org"}), DownloadBudget(536_870_912, 120)
    )
    if (
        client.hosts != frozenset({"registry.npmjs.org"})
        or client.budget.remaining_bytes > 536_870_912
    ):
        raise ValueError("Public cache downloader policy exceeds its exact allowlist/budget")
    initial = client.budget.remaining_bytes
    count = 0
    try:
        async with asyncio.timeout(900):
            for package in manifest.packages:
                await client.fetch(package.url, root / package.filename, package.integrity)
                count += 1
        return PublicPackageReceipt(
            manifest=manifest,
            downloaded_bytes=initial - client.budget.remaining_bytes,
            downloaded_packages=count,
        )
    finally:
        if owned:
            await client.close()


def _prepare(root: Path) -> None:
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        private_directory(descriptor)
    finally:
        os.close(descriptor)
