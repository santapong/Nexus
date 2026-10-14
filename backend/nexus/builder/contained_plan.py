"""PhaseA fixed selector descriptions; no process, current parent evidence or execution grant."""

from typing import Literal

from pydantic import Field

from nexus.builder.contracts import BuilderValue
from nexus.builder.csv_behavior_wrapper import mapping_sha256
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.node_recipe import command_policies, command_references
from nexus.builder.node_v4_assets import csv_wrapper_sha256
from nexus.builder.node_v4_recipe import v4_recipe_sha256
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.runtime_identity import RUNTIME_V2, V2_GLOBAL_ARGUMENTS, V2_RUN_ARGUMENTS


class ContainedSelectorDescription(BuilderValue):
    """Closed descriptive output; trusted config/live scope/observer ABI remains unimplemented."""

    runtime_recipe: Literal["nexus.builder.runtime.v2"] = RUNTIME_V2
    global_arguments: tuple[Literal["--cgroup-manager=cgroupfs"], ...] = Field(
        default=V2_GLOBAL_ARGUMENTS, min_length=1, max_length=1
    )
    run_arguments: tuple[Literal["--cgroups=split"], ...] = Field(
        default=V2_RUN_ARGUMENTS, min_length=1, max_length=1
    )
    execution_enabled: Literal[False] = False


def describe_contained_selectors(
    spec: BuilderExecutionSpec, policy: BuilderToolPolicy
) -> ContainedSelectorDescription:
    """Exact new descriptions only; existing runner/runtime_argv reject v2 before execution."""
    spec.require_descriptive_policy(policy)
    if spec.runtime_recipe != RUNTIME_V2:
        raise ValueError("Contained selector description requires explicit runtime v2")
    _require_node_method(spec, policy)
    return ContainedSelectorDescription()


def _require_node_method(spec: BuilderExecutionSpec, policy: BuilderToolPolicy) -> None:
    """V4 pins command/assets independently of engine; default/legacy Node versions deny v2."""
    pins = spec.runtime_inputs
    if pins is None:
        return
    if (
        pins.recipe != "nexus.builder.node.v4"
        or pins.command_recipe_sha256 != v4_recipe_sha256()
        or pins.csv_regression is None
        or pins.csv_regression.mapping_sha256 != mapping_sha256()
        or pins.csv_regression.wrapper_sha256 != csv_wrapper_sha256()
        or policy.commands != command_policies()
        or spec.job.commands != command_references()
    ):
        raise ValueError("Runtime v2 description requires the exact supported Node v4 tuple")
