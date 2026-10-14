"""Explicit local public stage CLI; it does not register or execute company work."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from nexus.builder.process import engine_environment, limited_stream
from nexus.builder.public_download import DownloadBudget, PublicDownloader
from nexus.builder.public_image import (
    NODE_DIGEST,
    PublicImageReceipt,
    file_sha256,
    stage_public_node,
)
from nexus.builder.snapshot import private_directory

PUBLIC_HOSTS = frozenset(
    {
        "auth.docker.io",
        "registry-1.docker.io",
        "production.cloudfront.docker.com",
        "registry.npmjs.org",
    }
)
PNPM_URL = "https://registry.npmjs.org/pnpm/-/pnpm-9.12.0.tgz"
PNPM_INTEGRITY = (
    "sha512-Sr9yUITXvLr71yi/x77mHy95H5d/2HVCs1edyyNQTRcNRjN5ReTGZIXNEtWIoMD"
    "lcO2cR358zdhQfPBfP5Lqyg=="
)


def require_stage_directory(root: Path) -> None:
    if not root.is_absolute() or root.resolve(strict=True) != root:
        raise ValueError("Local image stage must use an exact ordinary private directory")
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        private_directory(descriptor)
    finally:
        os.close(descriptor)
    if os.statvfs(root).f_bavail * os.statvfs(root).f_frsize < 3_221_225_472:
        raise ValueError("Local stage lacks the reviewed measured 3GiB storage reservation")


async def download(root: Path) -> None:
    await asyncio.to_thread(require_stage_directory, root)
    downloader = PublicDownloader(PUBLIC_HOSTS, DownloadBudget(629_145_600, 600))
    try:
        receipt = await stage_public_node(root, downloader)
    finally:
        await downloader.close()
    await asyncio.to_thread(
        (root / "node-download.json").write_text, receipt.model_dump_json(indent=2)
    )
    downloader = PublicDownloader(
        frozenset({"registry.npmjs.org"}), DownloadBudget(33_554_432, 120)
    )
    try:
        size = await downloader.fetch(PNPM_URL, root / "pnpm-9.12.0.tgz", PNPM_INTEGRITY)
    finally:
        await downloader.close()
    await asyncio.to_thread(
        (root / "pnpm-download.json").write_text,
        json.dumps(
            {
                "version": "9.12.0",
                "integrity": PNPM_INTEGRITY,
                "byte_length": size,
                "scope": "public verified tarball only; no installation performed",
            },
            indent=2,
        ),
    )


def load_argv(root: Path) -> tuple[str, ...]:
    return (
        "/usr/bin/podman",
        "--remote=false",
        "load",
        "--quiet",
        "--input",
        str(root / "node-amd64.oci.tar"),
    )


async def _engine(argv: tuple[str, ...], root: Path) -> bytes:
    environment = engine_environment()
    environment["REGISTRY_AUTH_FILE"] = str(root / "empty-auth.json")
    process = await asyncio.create_subprocess_exec(
        *argv,
        env=environment,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None and process.stderr is not None
    out = asyncio.create_task(limited_stream(process.stdout, 1_048_576))
    err = asyncio.create_task(limited_stream(process.stderr, 1_048_576))
    try:
        async with asyncio.timeout(300):
            values = await asyncio.gather(out, err, process.wait())
        if values[2] != 0:
            raise ValueError("Bounded local offline image operation failed")
        return values[0]
    finally:
        if process.returncode is None:
            process.kill()
        for task in (out, err):
            if not task.done():
                task.cancel()
        await asyncio.gather(out, err, return_exceptions=True)
        await asyncio.wait_for(process.communicate(), timeout=2)


async def load(root: Path) -> None:
    await asyncio.to_thread(require_stage_directory, root)
    receipt = PublicImageReceipt.model_validate_json(
        await asyncio.to_thread((root / "node-download.json").read_bytes)
    )
    actual = await asyncio.to_thread(file_sha256, root / "node-amd64.oci.tar")
    if receipt.digest != NODE_DIGEST or actual != receipt.archive_sha256:
        raise ValueError("Offline image archive changed after verified staging")
    await asyncio.to_thread((root / "empty-auth.json").write_text, '{"auths":{}}')
    await _engine(load_argv(root), root)
    raw = await _engine(
        ("/usr/bin/podman", "--remote=false", "image", "inspect", receipt.config_digest), root
    )
    value = json.loads(raw)[0]
    if value["Architecture"] != "amd64" or value["Os"] != "linux":
        raise ValueError("Loaded image platform differs")
    if value["Id"].removeprefix("sha256:") != receipt.config_digest[7:]:
        raise ValueError("Loaded image config differs")
    await asyncio.to_thread(
        (root / "node-loaded.json").write_text,
        json.dumps(
            {
                "image_id": value["Id"],
                "platform": "linux/amd64",
                "source_manifest": NODE_DIGEST,
                "archive_sha256": actual,
                "repo_digests": value.get("RepoDigests", []),
                "scope": "local public image staged only; no builder/ARM64 qualification",
            },
            indent=2,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("download", "load"))
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    try:
        asyncio.run(download(args.stage) if args.phase == "download" else load(args.stage))
    except Exception as exc:
        # No response URL/query/body or anonymous bearer is written on failure.
        (args.stage / f"{args.phase}-failed.json").write_text(
            json.dumps(
                {
                    "phase": args.phase,
                    "error_class": type(exc).__name__,
                    "scope": "stage incomplete",
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
