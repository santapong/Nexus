"""Node runtime adds only server-qualified readonly public inputs to the bounded job."""

from __future__ import annotations

from pathlib import Path

from nexus.builder.contracts import BuilderCapabilities
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.node_config import NodeRuntimeConfig
from nexus.builder.node_input_files import managed_path
from nexus.builder.node_recipe import require_node_recipe
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.runtime_plan import PreparedSources, runtime_argv


def node_argv(
    spec: BuilderExecutionSpec,
    policy: BuilderToolPolicy,
    capabilities: BuilderCapabilities,
    sources: PreparedSources,
    base: Path,
    config: NodeRuntimeConfig,
) -> tuple[str, ...]:
    if spec.runtime_inputs != config.pins or policy.runtime_inputs != config.pins:
        raise ValueError("Native Node server-qualified inputs differ from exact proposal/policy")
    require_node_recipe(spec, policy, execution=True)
    for path in (config.tools, config.cache, base / "node-commands", base / "loopback-hosts"):
        managed_path(path)
    original = runtime_argv(spec, policy, capabilities, sources, base / "entrypoint.sh")
    original = tuple(
        value.replace("/scratch:rw,nodev,nosuid,noexec,", "/scratch:rw,nodev,nosuid,exec,")
        if value.startswith("/scratch:rw,nodev,nosuid,noexec,")
        else value
        for value in original
    )
    additions = (
        "--volume",
        f"{config.tools}:/tools:ro",
        "--volume",
        f"{config.cache}:/cache/store:ro",
        "--volume",
        f"{base / 'node-commands'}:/node-commands:ro",
        "--volume",
        f"{base / 'loopback-hosts'}:/etc/hosts:ro",
        "--env=NPM_CONFIG_USERCONFIG=/node-commands/offline.npmrc",
        "--env=PNPM_DISABLE_SELF_UPDATE_CHECK=1",
        "--env=NPM_CONFIG_IGNORE_PNPMFILE=true",
        "--env=NPM_CONFIG_ENABLE_PRE_POST_SCRIPTS=false",
    )
    return (*original[:-2], *additions, *original[-2:])
