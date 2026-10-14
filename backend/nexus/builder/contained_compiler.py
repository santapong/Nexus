"""Closed v2 descriptions reuse renderers without changing ledger identity or permits."""

from pathlib import Path

from nexus.builder.contained_plan import describe_contained_selectors
from nexus.builder.contracts import BuilderCapabilities
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.node_config import NodeRuntimeConfig
from nexus.builder.node_recipe import node_script
from nexus.builder.node_runtime_plan import node_argv
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.runtime_identity import RUNTIME_V1
from nexus.builder.runtime_plan import PreparedSources, runtime_argv, runtime_script
from nexus.company.management.canonical import canonical_sha256


def _rendering_views(
    spec: BuilderExecutionSpec,
    policy: BuilderToolPolicy,
) -> tuple[BuilderExecutionSpec, BuilderToolPolicy]:
    """Internal rendering views never replace the original immutable v2 action/spec."""
    describe_contained_selectors(spec, policy)
    view_policy = BuilderToolPolicy.model_validate(
        policy.model_copy(
            update={
                "runtime_recipe": RUNTIME_V1,
                "runtime_method_sha256": None,
            }
        ).model_dump()
    )
    view_spec = BuilderExecutionSpec.model_validate(
        spec.model_copy(
            update={
                "runtime_recipe": RUNTIME_V1,
                "policy_sha256": canonical_sha256(view_policy),
            }
        ).model_dump()
    )
    view_spec.require_policy(view_policy)
    return view_spec, view_policy


def described_contained_script(spec: BuilderExecutionSpec, policy: BuilderToolPolicy) -> str:
    """Return exact generic or qualified Nodev4 script bytes; no process or source write."""
    view_spec, view_policy = _rendering_views(spec, policy)
    return (
        node_script(view_spec, view_policy)
        if spec.runtime_inputs is not None
        else runtime_script(view_spec, view_policy)
    )


def described_contained_argv(
    spec: BuilderExecutionSpec,
    policy: BuilderToolPolicy,
    capabilities: BuilderCapabilities,
    sources: PreparedSources,
    entrypoint: Path,
    *,
    node_config: NodeRuntimeConfig | None = None,
) -> tuple[str, ...]:
    """Use full current renderer validation, adding only the two closed engine selectors."""
    view_spec, view_policy = _rendering_views(spec, policy)
    if spec.runtime_inputs is not None:
        if entrypoint.name != "entrypoint.sh":
            raise ValueError("Contained Node description requires its fixed entrypoint")
        if node_config is None:
            raise ValueError("Contained Node description requires exact configured inputs")
        original = node_argv(
            view_spec, view_policy, capabilities, sources, entrypoint.parent, node_config
        )
    else:
        if node_config is not None:
            raise ValueError("Generic contained description cannot attach Node inputs")
        original = runtime_argv(view_spec, view_policy, capabilities, sources, entrypoint)
    if original[:3] != ("/usr/bin/podman", "--remote=false", "run"):
        raise ValueError("Original runtime renderer differs from the fixed engine ABI")
    return (
        *original[:2],
        "--cgroup-manager=cgroupfs",
        *original[2:3],
        "--cgroups=split",
        *original[3:],
    )
