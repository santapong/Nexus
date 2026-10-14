"""Actual method chaining/staging/witness unit proof; no native permit/process/PG claim."""

from pathlib import Path
from typing import cast

import pytest

from nexus.builder.engineering_node_runner import EngineeringNodeBuilderRunner
from nexus.builder.engineering_runner import EngineeringNativeBuilderRunner
from nexus.builder.engineering_witness import load_witness
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.node_config import NodeRuntimeConfig
from nexus.builder.node_runner import NodeNativeBuilderRunner
from nexus.builder.node_v4_assets import csv_wrapper_source
from nexus.builder.runner import NativeBuilderRunner
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.management.canonical import canonical_sha256
from nexus.tests.node_v4_support import described_v4_check


def test_explicit_mro_inherits_single_generic_run_and_node_invoke_engineering_recovery() -> None:
    assert EngineeringNodeBuilderRunner.__mro__[1:4] == (
        EngineeringNativeBuilderRunner,
        NodeNativeBuilderRunner,
        NativeBuilderRunner,
    )
    assert EngineeringNodeBuilderRunner.run is NativeBuilderRunner.run
    assert EngineeringNodeBuilderRunner.invoke is NodeNativeBuilderRunner.invoke
    assert EngineeringNodeBuilderRunner.reconcile is EngineeringNativeBuilderRunner.reconcile


async def test_prepare_runs_node_pin_asset_stage_then_actual_engineering_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Unit isolates only generic source acquisition and config filesystem qualification.
    # Actual Node method and actual witness capture execute; this is not native execution proof.
    import hashlib

    item = described_v4_check()
    assert item.author.spec.runtime_inputs is not None
    lock = b"synthetic-lock"
    pins = item.author.spec.runtime_inputs.model_copy(
        update={"lock_sha256": hashlib.sha256(lock).hexdigest()}
    )
    policy = item.declaration.policy.model_copy(update={"runtime_inputs": pins})
    spec = item.author.spec.model_copy(
        update={"runtime_inputs": pins, "policy_sha256": canonical_sha256(policy)}
    )
    base = tmp_path / "job"
    base.mkdir(mode=0o700)
    for phase in ("baseline", "post"):
        root = base / phase
        root.mkdir(mode=0o700)
        folder = root / "packages/shared/src/csv"
        folder.mkdir(parents=True)
        (root / "pnpm-lock.yaml").write_bytes(lock)
        (folder / "index.ts").write_text(phase + "-module")
        (folder / "csv.test.ts").write_text(phase + "-test")
    instance = EngineeringNodeBuilderRunner.__new__(EngineeringNodeBuilderRunner)
    instance.policy = policy
    instance.config = NodeRuntimeConfig(
        pins,
        tmp_path / "tool.tar",
        tmp_path / "tools",
        tmp_path / "cache.tar",
        tmp_path / "cache",
        tmp_path / "manifest",
    )
    observed = []

    async def qualified(self: NodeRuntimeConfig) -> None:
        observed.append("qualified")

    async def source(
        self: NativeBuilderRunner, value: BuilderExecutionSpec, guard: BuilderSourceGuard
    ) -> Path:
        observed.append("source")
        assert value == spec
        return base

    monkeypatch.setattr(NodeRuntimeConfig, "revalidate", qualified)
    monkeypatch.setattr(NativeBuilderRunner, "prepare", source)
    guard = cast(
        BuilderSourceGuard, object()
    )  # Generic acquisition is isolated; guard is not consumed.
    assert await instance.prepare(spec, guard) == base
    assert observed == ["qualified", "source"]
    assert (base / "node-commands/csv-test-wrapper.cjs").read_text() == csv_wrapper_source()
    assert load_witness(base, spec).spec_sha256 == canonical_sha256(spec)
