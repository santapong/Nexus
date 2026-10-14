"""Actual ordinary baseline/post inventories stored privately before native intent."""

from __future__ import annotations

import os
from pathlib import Path

from nexus.builder.engineering_contracts import EngineeringChangedFile, EngineeringSourceWitness
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.patch_inventory import inventory, inventory_digest
from nexus.builder.paths import open_regular, permitted_path
from nexus.company.management.canonical import canonical_sha256

WITNESS_PATH = "engineering-witness.json"


def capture_witness(base: Path, spec: BuilderExecutionSpec) -> EngineeringSourceWitness:
    if spec.protected_patch is None or spec.protected_patch.byte_length == 0:
        raise ValueError("Engineering run needs its actual nonempty protected patch")
    first, second = inventory(base / "baseline"), inventory(base / "post")
    names = sorted(
        name for name in first.keys() | second.keys() if first.get(name) != second.get(name)
    )
    if (
        not names
        or len(names) > 16
        or any(not permitted_path(name, spec.job.write_paths) for name in names)
    ):
        raise ValueError("Engineering change inventory exceeds exact allowed paths")
    value = EngineeringSourceWitness(
        spec_sha256=canonical_sha256(spec),
        source=spec.job.source,
        patch_sha256=spec.protected_patch.sha256,
        baseline_inventory_sha256=inventory_digest(first),
        post_inventory_sha256=inventory_digest(second),
        changes=tuple(
            EngineeringChangedFile(
                path=name,
                before_sha256=first[name][0] if name in first else None,
                after_sha256=second[name][0] if name in second else None,
            )
            for name in names
        ),
    )
    path = base / WITNESS_PATH
    with path.open("xb") as stream:
        stream.write(value.model_dump_json().encode())
    path.chmod(0o600)
    return value


def load_witness(base: Path, spec: BuilderExecutionSpec) -> EngineeringSourceWitness:
    descriptor = open_regular(base, WITNESS_PATH)
    try:
        raw = os.read(descriptor, 16385)
        if len(raw) > 16384 or os.read(descriptor, 1):
            raise ValueError("Engineering source witness exceeds its complete bound")
    finally:
        os.close(descriptor)
    value = EngineeringSourceWitness.model_validate_json(raw)
    if (value.spec_sha256, value.source, value.patch_sha256) != (
        canonical_sha256(spec),
        spec.job.source,
        spec.job.patch_sha256,
    ):
        raise ValueError("Engineering source witness binds another native job")
    return value
