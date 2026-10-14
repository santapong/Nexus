"""Post-extraction public-only status/mode probe; no project install or network."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from nexus.builder.cache_import_plan import IMAGE, _isolation
from nexus.builder.local_cache_probe import _probe_environment
from nexus.builder.process import engine_environment, limited_stream
from nexus.builder.public_image import file_sha256

NAME = "nexus-builder-cache-readonly-probe-20261014-v1"
ARCHIVE_SHA = "0a2e63c465bf19598d7814646219b492ae870fe91e87eddcc5dd13e69d32c239"


def script() -> str:
    return (
        "\n".join(
            (
                "#!/bin/sh",
                "set -eu",
                "mkdir -p /tmp/home; cd /tmp",
                "node /tools/package/bin/pnpm.cjs --version",
                "node /tools/package/bin/pnpm.cjs store status --store-dir /cache/store",
                "if touch /cache/store/forbidden-write 2>/dev/null; then exit 9; fi",
                'test -x "/cache/store/$(cat /inputs/exec-path)"',
                "printf 'QUALIFICATION post_extraction_readonly_status_execmode_only\\n'",
            )
        )
        + "\n"
    )


def argv(root: Path, tools: Path, cache: Path) -> tuple[str, ...]:
    return (
        "/usr/bin/podman",
        "--remote=false",
        "run",
        "--rm",
        "--name",
        NAME,
        "--label",
        f"nexus.builder.cache_readonly_probe={NAME}",
        *_isolation(),
        "--cpus=2",
        "--memory=268435456",
        "--memory-swap=268435456",
        "--pids-limit=32",
        "--timeout=30",
        "--tmpfs",
        "/tmp:rw,nodev,nosuid,noexec,size=8388608,mode=1777",
        "--volume",
        f"{tools}:/tools:ro",
        "--volume",
        f"{cache}:/cache/store:ro",
        "--volume",
        f"{root / 'inputs'}:/inputs:ro",
        "--volume",
        f"{root / 'inputs' / 'resolv.conf'}:/etc/resolv.conf:ro",
        *_probe_environment(),
        "--entrypoint=/bin/sh",
        IMAGE,
        "/inputs/entrypoint.sh",
    )


def prepare(root: Path, cache: Path) -> None:
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    inputs = root / "inputs"
    inputs.mkdir(mode=0o700)
    values = sorted(
        str(p.relative_to(cache))
        for p in cache.rglob("*")
        if p.is_file() and p.stat().st_mode & 0o100
    )
    if not values:
        raise ValueError("Qualified cache has no preserved executable mode")
    (inputs / "exec-path").write_text(values[0])
    (inputs / "resolv.conf").write_bytes(b"")
    (inputs / "empty-auth.json").write_text('{"auths":{}}')
    (inputs / "offline.npmrc").write_text(
        "offline=true\nignore-scripts=true\nverify-store-integrity=true\ncache-dir=/tmp/cache\nstate-dir=/tmp/state\n"
    )
    (inputs / "entrypoint.sh").write_text(script())


async def run(root: Path, tools: Path, cache: Path, archive: Path) -> None:
    if await asyncio.to_thread(file_sha256, archive) != ARCHIVE_SHA:
        raise ValueError("Qualified cache archive changed before readonly probe")
    await asyncio.to_thread(prepare, root, cache)
    env = engine_environment()
    env["REGISTRY_AUTH_FILE"] = str(root / "inputs" / "empty-auth.json")
    process = await asyncio.create_subprocess_exec(
        *argv(root, tools, cache),
        env=env,
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
                    "scope": "public readonly cache status/modes only",
                    "archive_sha256": ARCHIVE_SHA,
                    "argv": argv(root, tools, cache),
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
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("root", "tools", "cache", "archive"):
        p.add_argument("--" + key, required=True, type=Path)
    a = p.parse_args()
    asyncio.run(run(a.root, a.tools, a.cache, a.archive))


if __name__ == "__main__":
    main()
