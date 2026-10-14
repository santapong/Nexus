"""One explicit public-only offline pnpm CAS/lock compatibility probe; no company work."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from nexus.builder.local_toolchain import PNPM_INTEGRITY
from nexus.builder.process import engine_environment, limited_stream
from nexus.builder.public_tool_extract import extract_public_tool
from nexus.builder.snapshot import private_directory

IMAGE = (
    "localhost/nexus-node-22.23.3-bookworm@"
    "sha256:c4d5523090a817b7aa86d2111241fdd4f66d1e27782b44160e6aa63b357ecb2d"
)
NAME = "nexus-builder-pnpm-probe-20261014-v1"


def prepare(root: Path, tarball: Path) -> None:
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        private_directory(descriptor)
    finally:
        os.close(descriptor)
    fd = os.open(tarball, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        raw = source.read(33_554_433)
    extract_public_tool(raw, PNPM_INTEGRITY, root / "tools")
    inputs = root / "inputs"
    inputs.mkdir(mode=0o700)
    (inputs / "package.json").write_text(
        json.dumps({"private": True, "dependencies": {"pnpm": "9.12.0"}})
    )
    (inputs / "pnpm-lock.yaml").write_text(
        "lockfileVersion: '9.0'\nsettings:\n  autoInstallPeers: true\n"
        "  excludeLinksFromLockfile: false\nimporters:\n  .:\n    dependencies:\n"
        "      pnpm:\n        specifier: 9.12.0\n        version: 9.12.0\n"
        "packages:\n  pnpm@9.12.0:\n    resolution:\n      integrity: " + PNPM_INTEGRITY + "\n"
        "    engines: {node: '>=18.12'}\n    hasBin: true\nsnapshots:\n  pnpm@9.12.0: {}\n"
    )
    (inputs / "offline.npmrc").write_text(
        "offline=true\nignore-scripts=true\nverify-store-integrity=true\nside-effects-cache=false\n"
        "registry=https://registry.npmjs.org/\nstore-dir=/cache/store\ncache-dir=/tmp/cache\n"
        "state-dir=/tmp/state\n"
    )
    (inputs / "resolv.conf").write_bytes(b"")
    (inputs / "empty-auth.json").write_text('{"auths":{}}')
    (inputs / "entrypoint.sh").write_text(script())


def script() -> str:
    return (
        "\n".join(
            (
                "#!/bin/sh",
                "set -eu",
                "mkdir -p /tmp/home /cache/store /scratch/project",
                "cp /inputs/package.json /inputs/pnpm-lock.yaml /scratch/project/",
                "cd /scratch/project",
                "printf 'NODE '; node --version",
                "printf 'PNPM '; node /tools/package/bin/pnpm.cjs --version",
                "node /tools/package/bin/pnpm.cjs store add /downloads/pnpm-9.12.0.tgz "
                "--store-dir /cache/store",
                "node /tools/package/bin/pnpm.cjs install --offline --ignore-scripts "
                "--frozen-lockfile --store-dir /cache/store",
                "printf 'INSTALLED_PNPM '; node node_modules/pnpm/bin/pnpm.cjs --version",
                "node /tools/package/bin/pnpm.cjs store status --store-dir /cache/store",
                "du -sb /cache/store /scratch/project",
                "printf 'QUALIFICATION offline_cas_lock_only\\n'",
            )
        )
        + "\n"
    )


def argv(root: Path, tarball: Path) -> tuple[str, ...]:
    return (
        "/usr/bin/podman",
        "--remote=false",
        "run",
        "--rm",
        "--name",
        NAME,
        *_probe_labels(),
        "--pull=never",
        "--network=none",
        "--http-proxy=false",
        "--read-only",
        "--read-only-tmpfs=false",
        "--image-volume=ignore",
        "--no-hosts",
        "--no-hostname",
        "--passwd=false",
        "--no-healthcheck",
        "--log-driver=none",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pid=private",
        "--ipc=private",
        "--uts=private",
        "--cgroupns=private",
        "--cpus=2",
        "--memory=268435456",
        "--memory-swap=268435456",
        "--pids-limit=32",
        "--timeout=30",
        "--tmpfs",
        "/cache:rw,nodev,nosuid,noexec,size=67108864,mode=0700",
        "--tmpfs",
        "/scratch:rw,nodev,nosuid,noexec,size=33554432,mode=0700",
        "--tmpfs",
        "/tmp:rw,nodev,nosuid,noexec,size=8388608,mode=1777",
        "--volume",
        f"{root / 'tools'}:/tools:ro",
        "--volume",
        f"{root / 'inputs'}:/inputs:ro",
        "--volume",
        f"{tarball}:/downloads/pnpm-9.12.0.tgz:ro",
        "--volume",
        f"{root / 'inputs' / 'resolv.conf'}:/etc/resolv.conf:ro",
        *_probe_environment(),
        "--entrypoint=/bin/sh",
        IMAGE,
        "/inputs/entrypoint.sh",
    )


def _probe_environment() -> tuple[str, ...]:
    return (
        "--env=HOME=/tmp/home",
        "--env=NPM_CONFIG_USERCONFIG=/inputs/offline.npmrc",
        "--env=CI=1",
        "--env=PNPM_DISABLE_SELF_UPDATE_CHECK=1",
    )


def _probe_labels() -> tuple[str, ...]:
    return ("--label", f"nexus.builder.cache_probe={NAME}")


async def run(root: Path, tarball: Path) -> None:
    await asyncio.to_thread(prepare, root, tarball)
    environment = engine_environment()
    environment["REGISTRY_AUTH_FILE"] = str(root / "inputs" / "empty-auth.json")
    process = await asyncio.create_subprocess_exec(
        *argv(root, tarball),
        env=environment,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None and process.stderr is not None
    out = asyncio.create_task(limited_stream(process.stdout, 65536))
    err = asyncio.create_task(limited_stream(process.stderr, 65536))
    try:
        async with asyncio.timeout(32):
            values = await asyncio.gather(out, err, process.wait())
        await asyncio.to_thread(
            (root / "receipt.json").write_text,
            json.dumps(
                {
                    "scope": "public offline pnpm compatibility only",
                    "argv": argv(root, tarball),
                    "exit_code": values[2],
                    "stdout": values[0].decode(),
                    "stderr": values[1].decode(),
                },
                indent=2,
            ),
        )
    finally:
        if process.returncode is None:
            process.kill()
        for task in (out, err):
            if not task.done():
                task.cancel()
        await asyncio.gather(out, err, return_exceptions=True)
        await asyncio.wait_for(process.communicate(), timeout=2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--tarball", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.root, args.tarball))


if __name__ == "__main__":
    main()
