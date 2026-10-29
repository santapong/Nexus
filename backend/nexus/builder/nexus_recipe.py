"""One concrete Nexus Python/npm policy over the unchanged contained native engine."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.coding_templates import CodingBuilderServices
from nexus.builder.contained_services import ContainmentServices
from nexus.builder.contracts import (
    BuilderArtifact,
    BuilderCapabilities,
    BuilderValue,
    CommandRef,
    Digest,
    RepositoryPin,
    Symbol,
)
from nexus.builder.engineering_artifacts import EngineeringArtifactPublisher
from nexus.builder.engineering_runner import EngineeringNativeBuilderRunner
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256
from nexus.builder.nexus_public_inputs import NexusPlatform, NexusPublicInputs, sha256
from nexus.builder.nexus_recipe_assets import assets_sha256
from nexus.builder.policy import BuilderCommandPolicy, BuilderToolPolicy
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.runtime_identity import RUNTIME_V2, RUNTIME_V2_METHOD_SHA256
from nexus.company.management.canonical import canonical_sha256
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_store import ExecutionStore

COMMAND_KEYS = ("backend", "frontend-test", "frontend-build", "behavior")
REQUIRED_SOURCE_PATHS = (
    "backend/pyproject.toml",
    "backend/uv.lock",
    "frontend/package.json",
    "frontend/package-lock.json",
    "backend/nexus/tests/unit/test_company_management_plans.py",
    "frontend/scripts/test-company-coding.mjs",
    "frontend/scripts/test-company-cycle-costs.mjs",
    "frontend/tsconfig.json",
    "frontend/vite.config.ts",
)
WRITE_PATHS = ("backend/nexus/company/management/canonical.py",)
ARTIFACT_PATHS = ("checks", "backend-dist", "frontend-dist")
IMAGE_PATTERN = r"^[a-z0-9][a-z0-9./_-]{2,200}@sha256:[0-9a-f]{64}$"


class NexusToolchainManifest(BuilderValue):
    """Image-resident source/input pins, with unresolved qualification explicitly absent.

    The final image digest lives outside these image bytes to avoid a self-hash cycle.
    Host wheel/build/npm receipts are preparation evidence, never cold image/native proof.
    None fields deliberately block policy construction until Root supplies actual facts.
    """

    schema_version: Literal["nexus.builder.python312-npm.v1"] = "nexus.builder.python312-npm.v1"
    source: RepositoryPin
    inputs: NexusPublicInputs
    source_files: tuple[BuilderArtifact, ...] = Field(min_length=9, max_length=9)
    assets_sha256: Digest
    python_version: Literal["3.12.9"] = "3.12.9"
    uv_version: Literal["0.12.5"] = "0.12.5"
    node_version: Literal["26.8.1"] = "26.8.1"
    npm_version: Literal["11.19.0"] = "11.19.0"
    base_image: str | None = Field(default=None, pattern=IMAGE_PATTERN)
    test_tree_sha256: Digest | None = None
    test_requirements_sha256: Digest | None = None
    build_tree_sha256: Digest | None = None
    node_tree_sha256: Digest | None = None
    cold_offline_receipt_sha256: Digest | None = None

    @model_validator(mode="after")
    def exact_source_and_assets(self) -> Self:
        if (
            self.source.repository_symbol != "nexus"
            or tuple(row.path for row in self.source_files) != REQUIRED_SOURCE_PATHS
            or self.assets_sha256 != assets_sha256()
            or tuple(row.sha256 for row in self.source_files[:4])
            != (
                self.inputs.pyproject_sha256,
                self.inputs.uv_lock_sha256,
                self.inputs.package_sha256,
                self.inputs.npm_lock_sha256,
            )
            or any(row.byte_length <= 0 or row.byte_length > 2_097_152 for row in self.source_files)
        ):
            raise ValueError("Nexus source/lock/recipe asset declaration differs")
        return self

    def require_qualified_inputs(self) -> None:
        """No inferred image/test dependency readiness from parse success or host receipts."""
        checked = NexusToolchainManifest.model_validate(self.model_dump())
        if any(
            getattr(checked, key) is None
            for key in (
                "base_image",
                "test_tree_sha256",
                "build_tree_sha256",
                "node_tree_sha256",
                "cold_offline_receipt_sha256",
                "test_requirements_sha256",
            )
        ) or not {"pytest", "pytest-asyncio", "anyio", "pydantic"} <= {
            row.name for row in checked.inputs.test_wheels
        }:
            raise ValueError("Nexus image/base/test closure/cold offline inputs are unqualified")


class NexusImageBinding(BuilderValue):
    """Root-supplied actual image qualification metadata; this description grants no permit."""

    reference: str = Field(pattern=IMAGE_PATTERN)
    image_id: Digest
    manifest_sha256: Digest
    platform: NexusPlatform
    qualification_sha256: Digest

    @model_validator(mode="after")
    def immutable_qualified_name(self) -> Self:
        # Reuse the actual policy registry/tag validation, without minting authority.
        reference = self.reference.split("@", 1)[0]
        if "/" not in reference or ":" in reference.split("/", 1)[1]:
            raise ValueError("Nexus image requires an immutable registry-qualified digest")
        registry = reference.split("/", 1)[0]
        if "." not in registry and registry != "localhost":
            raise ValueError("Nexus image registry is unavailable")
        return self


def manifest_wire(manifest: NexusToolchainManifest) -> bytes:
    """Stable bounded image-resident JSON; final image identity is a separate binding."""
    checked = NexusToolchainManifest.model_validate(manifest.model_dump())
    raw = json.dumps(
        checked.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    if len(raw) > 262144:
        raise ValueError("Nexus toolchain manifest exceeds its fixed image metadata bound")
    return raw


def manifest_sha256(manifest: NexusToolchainManifest) -> str:
    """Bind exact bytes consumed by every fixed command, not an unordered model dump."""
    return sha256(manifest_wire(manifest))


def command_references() -> tuple[CommandRef, ...]:
    """All four original checks are mandatory in baseline and post, in exact order."""
    return tuple(
        CommandRef(command_key=key, phase=phase)
        for phase in ("baseline", "post")
        for key in COMMAND_KEYS
    )


def make_nexus_policy(
    company_id: UUID,
    resource_symbol: Symbol,
    manifest: NexusToolchainManifest,
    image: NexusImageBinding,
) -> BuilderToolPolicy:
    """Produce only the fixed new recipe after explicit input/image binding validation."""
    manifest.require_qualified_inputs()
    image = NexusImageBinding.model_validate(image.model_dump())
    digest = manifest_sha256(manifest)
    if image.manifest_sha256 != digest or image.platform != manifest.inputs.platform:
        raise ValueError("Nexus image platform/manifest differs from exact qualified inputs")
    return BuilderToolPolicy(
        company_id=company_id,
        policy_symbol="nexus-python312-npm-v1",
        resource_symbol=resource_symbol,
        repository_symbol="nexus",
        image=image.reference,
        commands=tuple(
            BuilderCommandPolicy(
                command_key=key,
                directory=".",
                argv=(
                    "/usr/local/bin/python3.12",
                    "/opt/nexus-recipe/check.py",
                    key,
                    "--manifest-sha256",
                    digest,
                ),
            )
            for key in COMMAND_KEYS
        ),
        write_paths=WRITE_PATHS,
        artifact_paths=ARTIFACT_PATHS,
        runtime_inputs=None,
        runtime_recipe=RUNTIME_V2,
        runtime_method_sha256=RUNTIME_V2_METHOD_SHA256,
        full_execution_method_sha256=CONTAINED_EXECUTION_METHOD_SHA256,
    )


def require_nexus_recipe(
    spec: BuilderExecutionSpec,
    policy: BuilderToolPolicy,
    manifest: NexusToolchainManifest,
    image: NexusImageBinding,
) -> None:
    """Exact data join only; original C source/parent/lease/witness/effect guards still apply."""
    spec = BuilderExecutionSpec.model_validate(spec.model_dump())
    expected = make_nexus_policy(spec.job.company_id, policy.resource_symbol, manifest, image)
    spec.require_descriptive_policy(policy)
    if (
        policy != expected
        or spec.policy_sha256 != canonical_sha256(expected)
        or spec.runtime_inputs is not None
        or spec.job.commands != command_references()
        or spec.job.source != manifest.source
        or spec.job.write_paths != WRITE_PATHS
        or spec.job.artifact_paths != ARTIFACT_PATHS
        or "linux/" + spec.job.architecture != manifest.inputs.platform
        or spec.job.policy_symbol != policy.policy_symbol
        or spec.job.resource_symbol != policy.resource_symbol
    ):
        raise ValueError("Nexus native descriptor differs from the complete fixed recipe")


def compose_nexus_runner(
    factory: async_sessionmaker[AsyncSession],
    execution: ExecutionStore,
    effects: EffectStore,
    *,
    policy: BuilderToolPolicy,
    capabilities: BuilderCapabilities,
    image_id: str,
    results: BuilderResultStore,
    jobs_root: Path,
    publisher: EngineeringArtifactPublisher,
    containment: ContainmentServices,
    coding: CodingBuilderServices,
    manifest: NexusToolchainManifest,
    image: NexusImageBinding,
) -> EngineeringNativeBuilderRunner:
    """Compose the real unchanged engine; no source staging, SQL, parent observation or launch."""
    manifest.require_qualified_inputs()
    expected = make_nexus_policy(policy.company_id, policy.resource_symbol, manifest, image)
    if (
        policy != expected
        or image_id != image.image_id
        or type(execution) is not ExecutionStore
        or execution._factory is not factory
        or type(effects) is not EffectStore
        or effects._factory is not factory
        or type(publisher) is not EngineeringArtifactPublisher
        or publisher.factory is not factory
        or type(containment) is not ContainmentServices
        or type(results) is not BuilderResultStore
        or type(coding) is not CodingBuilderServices
        or coding.reader.factory is not factory
        or execution._management_catalog is not coding.reader.catalog
        or effects._management_catalog is not coding.reader.catalog
        or execution._management_artifacts is not coding.reader.artifacts
        or effects._management_artifacts is not coding.reader.artifacts
        or execution._management_freshness is not coding.reader.freshness
        or effects._management_freshness is not coding.reader.freshness
        or publisher.blobs is not coding.reader.blobs
        or publisher.containment_store is not containment.store
        or publisher.execution_method_sha256 != CONTAINED_EXECUTION_METHOD_SHA256
        or publisher.jobs_root != jobs_root
        or "linux/" + capabilities.architecture != image.platform
        or not capabilities.image_present
        or capabilities.qualified_image != image.reference
        or not capabilities.rootless
        or not capabilities.cgroup_v2
        or not {"cpu", "memory", "pids"} <= capabilities.controllers
        or not capabilities.hard_workspace_quota
        or not capabilities.network_none_verified
    ):
        raise ValueError("Nexus runner needs the same qualified concrete native graph")
    if (
        not jobs_root.is_absolute()
        or jobs_root.resolve(strict=True) != jobs_root
        or str(jobs_root).startswith(("/home/", "/root/"))
        or jobs_root.stat().st_uid != os.getuid()
        or stat.S_IMODE(jobs_root.stat().st_mode) != 0o700
    ):
        raise ValueError("Nexus jobs root must retain its private nonhome ownership")
    coding.require_composition()
    if any(
        row.template.policy != policy
        or row.template.repository != manifest.source
        or row.template.commands != command_references()
        for row in coding.entries
    ):
        raise ValueError("Nexus runner differs from fixed current C-origin E/EV templates")
    return EngineeringNativeBuilderRunner(
        factory,
        execution,
        effects,
        policy,
        capabilities,
        image_id,
        results,
        jobs_root,
        publisher,
        containment=containment,
    )
