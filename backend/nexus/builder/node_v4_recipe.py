"""Opt-in v4 fixed complete CSV/shared/web method; historical recipes stay unchanged."""

from __future__ import annotations

import hashlib
import json
import shlex

from nexus.builder.csv_behavior_wrapper import mapping_sha256
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.node_v4_assets import csv_wrapper_sha256, csv_wrapper_source
from nexus.builder.policy import BuilderToolPolicy


def v4_wrappers() -> dict[str, str]:
    """Keep four externally observed command keys while executing both full projects."""
    from nexus.builder.node_recipe import wrappers

    old = wrappers()
    shared = shlex.join(
        (
            "/usr/local/bin/node",
            "/tools/package/bin/pnpm.cjs",
            "--filter",
            "@stockflow/shared",
            "typecheck",
        )
    )
    web = shlex.join(
        (
            "/usr/local/bin/node",
            "/tools/package/bin/pnpm.cjs",
            "--filter",
            "@stockflow/web",
            "typecheck",
        )
    )
    old["typecheck"] = "#!/bin/sh\nset -e\n" + shared + "\n" + web + "\n"
    old["test"] = (
        "#!/bin/sh\nset -e\nexec /usr/local/bin/node /node-commands/csv-test-wrapper.cjs\n"
    )
    return old


def v4_recipe_sha256() -> str:
    """Hash fixed asset/mapping/transition and exact command bytes; no caller paths."""
    from nexus.builder.node_phase_cleanup import cleanup_script
    from nexus.builder.node_recipe import config_text, loopback_hosts, phase_transition, startup

    value = {
        "wrappers": v4_wrappers(),
        "csv_wrapper": csv_wrapper_source(),
        "mapping_sha256": mapping_sha256(),
        "offline_npmrc": config_text(),
        "loopback_hosts": loopback_hosts(),
        "startup": startup(),
        "baseline_cleanup_script": cleanup_script(),
        "phase_transition": phase_transition(),
        "scope": "full fixed shared/web suites; intended baseline-module regression probe",
        "workspace": "same bounded readonly-input/scratch/output envelope",
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def require_v4_recipe(spec: BuilderExecutionSpec, policy: BuilderToolPolicy) -> None:
    """Exactly bind reviewed CSV source/method/case pins before any native preparation."""
    from nexus.builder.node_recipe import command_policies, command_references

    spec.require_policy(policy)
    pins = spec.runtime_inputs
    if (
        pins is None
        or pins.recipe != "nexus.builder.node.v4"
        or pins.csv_regression is None
        or pins.command_recipe_sha256 != v4_recipe_sha256()
        or pins.csv_regression.mapping_sha256 != mapping_sha256()
        or pins.csv_regression.wrapper_sha256 != csv_wrapper_sha256()
        or policy.commands != command_policies()
        or spec.job.commands != command_references()
    ):
        raise ValueError("Node v4 differs from its complete fixed CSV method")
