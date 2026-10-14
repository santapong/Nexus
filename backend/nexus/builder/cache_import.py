"""Bound the one owned offline import, binary export, validation and private cache output."""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import suppress
from pathlib import Path

from nexus.builder.cache_archive import extract_cache
from nexus.builder.cache_import_plan import NAME, import_argv, import_script
from nexus.builder.cache_stream import StreamedCache, cache_stream
from nexus.builder.process import engine_environment, limited_stream, owned_engine
from nexus.builder.public_image import file_sha256
from nexus.builder.public_package_contracts import PublicPackageManifest


def prepare_import(root: Path, manifest: PublicPackageManifest) -> None:
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    inputs = root / "inputs"
    inputs.mkdir(mode=0o700)
    (inputs / "offline.npmrc").write_text(
        "offline=true\nignore-scripts=true\nverify-store-integrity=true\n"
        "side-effects-cache=false\nregistry=https://registry.npmjs.org/\nstore-dir=/cache/store\n"
        "cache-dir=/tmp/cache\nstate-dir=/tmp/state\n"
    )
    (inputs / "resolv.conf").write_bytes(b"")
    (inputs / "empty-auth.json").write_text('{"auths":{}}')
    (inputs / "entrypoint.sh").write_text(import_script(manifest))


async def stop_import() -> None:
    raw = await owned_engine(
        ("inspect", "--format", '{{index .Config.Labels "nexus.builder.cache_import"}}', NAME)
    )
    if raw.decode().strip() != NAME:
        raise ValueError("Public cache import owned identity differs")
    await owned_engine(("kill", "--signal=KILL", NAME))


async def import_cache(
    root: Path, downloads: Path, tools: Path, manifest: PublicPackageManifest
) -> None:
    await asyncio.to_thread(prepare_import, root, manifest)
    environment = engine_environment()
    environment["REGISTRY_AUTH_FILE"] = str(root / "inputs" / "empty-auth.json")
    process = await asyncio.create_subprocess_exec(
        *import_argv(root, downloads, tools),
        env=environment,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None and process.stderr is not None
    archive = root / "cache.tar"
    out = asyncio.create_task(cache_stream(process.stdout, archive))
    err = asyncio.create_task(limited_stream(process.stderr, 65536))
    try:
        async with asyncio.timeout(902):
            values = await asyncio.gather(out, err, process.wait())
        await _receipt(root, manifest, values[0], values[1], values[2])
        if values[2] != 0:
            raise ValueError("Public offline CAS cache import failed")
        await asyncio.to_thread(extract_cache, archive, root / "qualified-cache")
        await asyncio.to_thread(
            (root / "qualified-receipt.json").write_text,
            json.dumps(
                {
                    "scope": "verified public CAS store; not a project check",
                    "archive_sha256": await asyncio.to_thread(file_sha256, archive),
                    "manifest_sha256": hashlib.sha256(
                        manifest.model_dump_json().encode()
                    ).hexdigest(),
                },
                indent=2,
            ),
        )
    except (Exception, asyncio.CancelledError):
        with suppress(ValueError, TimeoutError):
            await stop_import()
        if process.returncode is None:
            process.kill()
        raise
    finally:
        for task in (out, err):
            if not task.done():
                task.cancel()
        await asyncio.gather(out, err, return_exceptions=True)
        await asyncio.wait_for(process.communicate(), timeout=2)


async def _receipt(
    root: Path, manifest: PublicPackageManifest, archive: StreamedCache, stderr: bytes, code: int
) -> None:
    value = {
        "scope": "public offline CAS cache only",
        "exit_code": code,
        "stderr": stderr.decode(),
        "archive": archive.model_dump(mode="json"),
        "manifest": manifest.model_dump(mode="json"),
    }
    await asyncio.to_thread((root / "import-receipt.json").write_text, json.dumps(value, indent=2))
