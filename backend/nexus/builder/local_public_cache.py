"""Separate public cache preparation; offline jobs never use registry access."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import os
from pathlib import Path

from nexus.builder.cache_import import import_cache
from nexus.builder.local_toolchain import PNPM_INTEGRITY
from nexus.builder.public_package_contracts import PublicPackageManifest
from nexus.builder.public_package_download import PublicPackageReceipt, download_packages
from nexus.builder.public_tool_extract import extract_public_tool
from nexus.builder.snapshot import private_directory

MANIFEST_SHA = "06ef2805b73fa8cae5ea93cbb6c857f6abe93773c1de9ed71603a3081cfce6ae"


def read_manifest(path: Path) -> PublicPackageManifest:
    with path.open("rb") as stream:
        raw = stream.read(1_048_577)
    if len(raw) > 1_048_576 or hashlib.sha256(raw).hexdigest() != MANIFEST_SHA:
        raise ValueError("Public cache manifest differs from the reviewed exact package set")
    return PublicPackageManifest.model_validate_json(raw)


def prepare_root(root: Path) -> None:
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        private_directory(fd)
    finally:
        os.close(fd)


async def download(root: Path, manifest_path: Path) -> None:
    manifest = await asyncio.to_thread(read_manifest, manifest_path)
    await asyncio.to_thread(prepare_root, root)
    receipt = await download_packages(root / "downloads", manifest)
    await asyncio.to_thread(
        (root / "download-receipt.json").write_text, receipt.model_dump_json(indent=2)
    )


def verify_tarballs(root: Path, manifest: PublicPackageManifest) -> None:
    for package in manifest.packages:
        descriptor = os.open(root / package.filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        digest = hashlib.sha512()
        size = 0
        with os.fdopen(descriptor, "rb") as stream:
            while raw := stream.read(65536):
                size += len(raw)
                if size > 536_870_912:
                    raise ValueError("Verified package tar exceeds complete stage bound")
                digest.update(raw)
        if package.integrity != "sha512-" + base64.b64encode(digest.digest()).decode():
            raise ValueError("Public package tar changed after verified download")


async def imported(root: Path, manifest_path: Path, pnpm_tar: Path) -> None:
    manifest = await asyncio.to_thread(read_manifest, manifest_path)
    receipt = PublicPackageReceipt.model_validate_json(
        await asyncio.to_thread((root / "download-receipt.json").read_bytes)
    )
    if receipt.manifest != manifest or receipt.downloaded_packages != len(manifest.packages):
        raise ValueError("Public package stage lacks its full exact receipt")
    await asyncio.to_thread(verify_tarballs, root / "downloads", manifest)
    with pnpm_tar.open("rb") as stream:
        raw = await asyncio.to_thread(stream.read, 33_554_433)
    await asyncio.to_thread(extract_public_tool, raw, PNPM_INTEGRITY, root / "tools")
    await import_cache(root / "import", root / "downloads", root / "tools", manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("download", "import"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--pnpm-tar", type=Path)
    args = parser.parse_args()
    if args.phase == "import" and args.pnpm_tar is None:
        raise SystemExit("Explicit verified pnpm tar is required")
    asyncio.run(
        download(args.root, args.manifest)
        if args.phase == "download"
        else imported(args.root, args.manifest, args.pnpm_tar)
    )


if __name__ == "__main__":
    main()
