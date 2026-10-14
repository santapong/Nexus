"""Harmless ordinary input archives exercise the server-only Node byte qualification."""

from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from pathlib import Path

from nexus.builder.cache_archive import extract_cache
from nexus.builder.node_config import NodeRuntimeConfig
from nexus.builder.node_contracts import NodeRuntimeInputs
from nexus.builder.node_recipe import recipe_sha256
from nexus.builder.public_package_contracts import PublicPackage, PublicPackageManifest, package_url
from nexus.builder.public_tool_extract import extract_public_tool


def configured_inputs(root: Path) -> NodeRuntimeConfig:
    tool = root / "tool.tgz"
    with tarfile.open(tool, "w:gz") as archive:
        add_file(archive, "package/bin/pnpm.cjs", b"public test fixture", 0o755)
    raw = tool.read_bytes()
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode()
    tools = root / "tools"
    extract_public_tool(raw, integrity, tools)
    cache = root / "cache.tar"
    with tarfile.open(cache, "w", format=tarfile.GNU_FORMAT) as archive:
        add_file(archive, "store/ordinary", b"verified fixture", 0o644)
        add_file(archive, "store/executable", b"verified executable", 0o755)
    extracted = root / "qualified"
    extract_cache(cache, extracted)
    manifest = root / "manifest.json"
    manifest.write_text(
        PublicPackageManifest(
            lock_sha256="5" * 64,
            packages=(
                PublicPackage(
                    name="pnpm",
                    version="9.12.0",
                    integrity=integrity,
                    url=package_url("pnpm", "9.12.0"),
                ),
            ),
        ).model_dump_json()
    )
    pins = NodeRuntimeInputs(
        tool_symbol="pnpm.v9_12",
        cache_symbol="fixture.pnpm.amd64.v1",
        image_id="1" * 64,
        node_version="22.23.3",
        pnpm_version="9.12.0",
        pnpm_archive_sha256=hashlib.sha256(raw).hexdigest(),
        pnpm_integrity=integrity,
        cache_archive_sha256=hashlib.sha256(cache.read_bytes()).hexdigest(),
        cache_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        lock_sha256="5" * 64,
        command_recipe_sha256=recipe_sha256(),
    )
    return NodeRuntimeConfig(pins, tool, tools, cache, extracted / "store", manifest)


def add_file(archive: tarfile.TarFile, name: str, raw: bytes, mode: int) -> None:
    row = tarfile.TarInfo(name)
    row.size, row.mode = len(raw), mode
    archive.addfile(row, io.BytesIO(raw))
