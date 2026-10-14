"""Manual disposable qualification configuration; never imported by production workers."""

from __future__ import annotations

import hashlib
from pathlib import Path

from nexus.builder.contracts import BuilderLimits, RepositoryPin
from nexus.builder.local_toolchain import PNPM_INTEGRITY
from nexus.builder.node_config import NodeRuntimeConfig
from nexus.builder.node_contracts import NodeRuntimeInputs
from nexus.builder.node_recipe import recipe_sha256
from nexus.builder.snapshot import committed_archive
from nexus.tests.builder_node_support import IMAGE_ID, TOOL_ARCHIVE, TOOL_ROOT

REPOSITORY = Path("/mnt/data/company/apps/Smart-Inventory")
PIN = RepositoryPin(
    repository_symbol="stockflow.nominated.20261014",
    commit="bb7cc00848bb650069543e843f826703d468058c",
    tree="e0ed0e5618d3dda4d0cde0fd2cdc5642a99c8ac2",
    archive_sha256="4e9d4164d29905837055a38ec42ab7c53b9796bc0df474ece61172ae5a10a507",
)
CACHE_ROOT = Path("/tmp/nexus-builder-stockflow-public-cache-20261014-v1")
MANIFEST = Path(
    "/mnt/data/nexus-implementation-evidence-2026-10-14/native-builder/stockflow-public-package-manifest-v1.json"
)


def public_config() -> NodeRuntimeConfig:
    pins = NodeRuntimeInputs(
        tool_symbol="pnpm.v9_12",
        cache_symbol="stockflow.nominated.pnpm.amd64.v1",
        image_id=IMAGE_ID,
        node_version="22.23.3",
        pnpm_version="9.12.0",
        pnpm_archive_sha256="a61b67ff6cc97af864564f4442556c22a04f2e5a7714fbee76a1011361d9b726",
        pnpm_integrity=PNPM_INTEGRITY,
        cache_archive_sha256="0a2e63c465bf19598d7814646219b492ae870fe91e87eddcc5dd13e69d32c239",
        cache_manifest_sha256="06ef2805b73fa8cae5ea93cbb6c857f6abe93773c1de9ed71603a3081cfce6ae",
        lock_sha256="57846422cd13346efdaf12bcde91d4d9e42c18eee21d7aafd5fa69b4a49877b3",
        command_recipe_sha256=recipe_sha256(),
    )
    return NodeRuntimeConfig(
        pins,
        TOOL_ARCHIVE,
        TOOL_ROOT,
        CACHE_ROOT / "import/cache.tar",
        CACHE_ROOT / "import/qualified-cache/store",
        MANIFEST,
    )


async def qualified_inputs() -> tuple[Path, RepositoryPin, NodeRuntimeConfig]:
    config = public_config()
    await config.revalidate()
    raw = await committed_archive(REPOSITORY, PIN)
    if hashlib.sha256(raw).hexdigest() != PIN.archive_sha256:
        raise ValueError("Nominated historical StockFlow source changed")
    return REPOSITORY, PIN, config


def qualification_limits() -> BuilderLimits:
    return BuilderLimits(
        cpu_millis=2000,
        memory_bytes=4_294_967_296,
        workspace_bytes=2_147_483_648,
        output_bytes=67_108_864,
        log_bytes=1_048_576,
        command_seconds=300,
        job_seconds=1200,
        pids=256,
    )
