"""Fixed complete Nexus E/EV templates; no description grants source or native permission."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self
from uuid import UUID

from pydantic import Field, model_validator

from nexus.builder.contracts import (
    Architecture,
    BuilderLimits,
    BuilderValue,
    CommandRef,
    Digest,
    RepositoryPin,
)
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.runtime_identity import RUNTIME_V2
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_publication_origin import CodingPublicationOriginReader
from nexus.company.management.plans import RunBinding
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.runtime_contracts import ExecutionLease

if TYPE_CHECKING:
    from nexus.builder.coding_guard import CodingBuilderSourceGuard


class CodingBuilderTemplate(BuilderValue):
    """Operator-fixed original C pair and complete check policy, not model-picked commands."""

    company_id: UUID
    goal_id: UUID
    admission_sha256: Digest
    c_action_id: UUID
    origin: ArtifactRevisionRef
    protected_patch: ArtifactRevisionRef
    source_metadata: ArtifactRevisionRef
    repository: RepositoryPin
    policy: BuilderToolPolicy
    architecture: Architecture
    commands: tuple[CommandRef, ...] = Field(min_length=2, max_length=8)
    write_paths: tuple[str, ...] = Field(min_length=1, max_length=16)
    artifact_paths: tuple[str, ...] = Field(min_length=1, max_length=16)
    limits: BuilderLimits
    output_resource: ResourceRef

    @model_validator(mode="after")
    def complete_configuration(self) -> Self:
        """No omitted declared check, alternate method or widened policy scope."""
        policy = self.policy
        keys = tuple(row.command_key for row in policy.commands)
        commands = tuple(
            CommandRef(command_key=key, phase=phase)
            for phase in ("baseline", "post")
            for key in keys
        )
        if (
            self.commands != commands
            or len(keys) > 4
            or self.write_paths != policy.write_paths
            or self.artifact_paths != policy.artifact_paths
            or policy.repository_symbol != self.repository.repository_symbol
            or policy.runtime_recipe != RUNTIME_V2
            or policy.full_execution_method_sha256 != CONTAINED_EXECUTION_METHOD_SHA256
            or len(set(self.write_paths)) != len(self.write_paths)
            or len(set(self.artifact_paths)) != len(self.artifact_paths)
            or self.protected_patch.byte_length > 32768
            or self.origin.byte_length > 131072
            or self.protected_patch.byte_length == 0
            or self.origin.byte_length == 0
            or any(
                row.company_id != self.company_id
                for row in (
                    self.origin,
                    self.protected_patch,
                    self.source_metadata,
                    self.output_resource,
                    policy,
                )
            )
            or (
                policy.runtime_inputs is not None
                and self.architecture != policy.runtime_inputs.architecture
            )
        ):
            raise ValueError("Nexus coding builder needs its complete exact current native policy")
        return self


def checked_template(value: CodingBuilderTemplate) -> CodingBuilderTemplate:
    """Validate original integer counts before serialization can normalize copied values."""
    if type(value) is not CodingBuilderTemplate:
        raise ValueError("Concrete coding builder template is required")
    BuilderLimits.model_validate(
        {key: getattr(value.limits, key) for key in BuilderLimits.model_fields}
    )
    for ref in (value.origin, value.protected_patch, value.source_metadata):
        if type(ref.byte_length) is not int:
            raise ValueError("Coding template has a changed reference bound")
    return CodingBuilderTemplate.model_validate(value.model_dump(warnings=False))


def require_coding_builder_spec(
    template: CodingBuilderTemplate,
    binding: RunBinding,
    spec: BuilderExecutionSpec,
    policy: BuilderToolPolicy,
    metadata: ArtifactRevisionRef,
) -> None:
    """Exact supplied data comparison; real native/source guards remain mandatory."""
    template = checked_template(template)
    BuilderLimits.model_validate(
        {key: getattr(spec.job.limits, key) for key in BuilderLimits.model_fields}
    )
    spec = BuilderExecutionSpec.model_validate(spec.model_dump(warnings=False))
    spec.require_descriptive_policy(policy)
    job = spec.job
    if (
        (job.company_id, job.task_id, job.trace_id, job.run_id, job.actor_id, job.workspace_id)
        != (
            binding.company_id,
            binding.task_id,
            binding.trace_id,
            binding.run_id,
            binding.actor_id,
            binding.workspace_id,
        )
        or (binding.workflow_name, binding.workflow_version, binding.model_profile)
        not in {
            ("engineering.change", "v1", "engineering.native.v1"),
            ("engineering.verify", "v1", "verification.native.v1"),
        }
        or policy != template.policy
        or spec.runtime_recipe != RUNTIME_V2
        or spec.runtime_inputs != policy.runtime_inputs
        or metadata != template.source_metadata
        or spec.protected_patch != template.protected_patch
        or spec.output_resource != template.output_resource
        or job.source != template.repository
        or job.patch_sha256 != template.protected_patch.sha256
        or job.policy_symbol != policy.policy_symbol
        or job.resource_symbol != policy.resource_symbol
        or (job.architecture, job.commands, job.write_paths, job.artifact_paths, job.limits)
        != (
            template.architecture,
            template.commands,
            template.write_paths,
            template.artifact_paths,
            template.limits,
        )
    ):
        raise ValueError("Exact Nexus coding native descriptor differs from its server template")


@dataclass(frozen=True)
class CodingBuilderEntry:
    binding: RunBinding
    template: CodingBuilderTemplate


@dataclass(frozen=True)
class CodingBuilderServices:
    """One sealed current C-origin reader and exactly the configured E/EV templates."""

    reader: CodingPublicationOriginReader
    entries: tuple[CodingBuilderEntry, ...]
    _pin: tuple[str, ...] = field(init=False, repr=False)
    _objects: tuple[object, ...] = field(init=False, repr=False)
    _retained_leases: list[ExecutionLease] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.reader) is not CodingPublicationOriginReader
            or type(self.entries) is not tuple
            or len(self.entries) != 2
        ):
            raise ValueError("Coding builder requires its concrete origin reader and E/EV pair")
        object.__setattr__(
            self,
            "_objects",
            (
                self.reader,
                self.reader.factory,
                self.reader.artifacts,
                self.reader.freshness,
                self.entries,
            ),
        )
        object.__setattr__(
            self, "_pin", tuple(canonical_sha256(row.template) for row in self.entries)
        )
        self.require_composition()

    def require_composition(self) -> None:
        """No coherent graph or template replacement across actual awaits."""
        self.reader.require_composition()
        if (
            any(
                a is not b
                for a, b in zip(
                    self._objects,
                    (
                        self.reader,
                        self.reader.factory,
                        self.reader.artifacts,
                        self.reader.freshness,
                        self.entries,
                    ),
                    strict=True,
                )
            )
            or tuple(canonical_sha256(row.template) for row in self.entries) != self._pin
        ):
            raise ValueError("Original coding builder services changed")
        resources = {row.symbol: row.resource for row in self.reader.catalog.resources}
        for row, slot in zip(self.entries, self.reader.admission.slots[5:7], strict=True):
            template = checked_template(row.template)
            if (
                type(row) is not CodingBuilderEntry
                or row.binding != slot.child.binding
                or template.company_id != self.reader.catalog.company_id
                or template.goal_id != self.reader.admission.goal.goal_id
                or template.admission_sha256 != canonical_sha256(self.reader.admission)
                or template.c_action_id != self.reader.rules.action_id
                or template.policy.resource_symbol != slot.tool.resource
                or template.output_resource != resources.get(slot.tool.resource)
            ):
                raise ValueError("Coding builder entry differs from actual configured E/EV")
        first, last = (row.template for row in self.entries)
        if (
            first.origin,
            first.protected_patch,
            first.repository,
            first.policy,
            first.commands,
            first.write_paths,
            first.artifact_paths,
            first.limits,
        ) != (
            last.origin,
            last.protected_patch,
            last.repository,
            last.policy,
            last.commands,
            last.write_paths,
            last.artifact_paths,
            last.limits,
        ):
            raise ValueError(
                "Independent E/EV must use the same original source/patch/check policy"
            )

    def pending_owners(self) -> tuple[object, ...]:
        """Descriptive real owners retained by this runtime service; no completion claim."""
        return self.reader.pending_owners()

    @property
    def retained_leases(self) -> tuple[ExecutionLease, ...]:
        """Actual acquisition metadata retained when a private read stops unresolved."""
        return tuple(self._retained_leases)

    def forget_settled_lease(self, lease: ExecutionLease) -> None:
        """Metadata only, after caller proves actual IO settlement and release/transfer."""
        if self.pending_owners():
            raise ValueError("Actual private-read owners remain unsettled")
        self._retained_leases[:] = [row for row in self._retained_leases if row is not lease]

    async def prepare_guard(
        self, original: BuilderSourceGuard, credential: AuthenticatedWorkerIdentity, *, end_us: int
    ) -> CodingBuilderSourceGuard:
        """Load real current actor sources outside CC; never decode caller origin proof."""
        from nexus.builder.coding_guard import CodingBuilderSourceGuard

        self.require_composition()
        if (
            type(original) is not BuilderSourceGuard
            or original.artifacts is not self.reader.artifacts
            or original.freshness is not self.reader.freshness
            or original.catalog is not self.reader.catalog
        ):
            raise ValueError("Coding source resolver differs from the exact shared source graph")
        rows = tuple(row for row in self.entries if row.binding.task_id == original.lease.task_id)
        if len(rows) != 1:
            raise ValueError("Coding E/EV binding is unavailable")
        row = rows[0]
        require_coding_builder_spec(
            row.template, row.binding, original.spec, original.policy, original.source.metadata
        )
        self._retained_leases.append(original.lease)
        proof = await self.reader.load(original.lease, credential, original.spec, end_us=end_us)
        self.require_composition()
        if proof.selection.references != (row.template.origin, row.template.protected_patch):
            raise ValueError("Actual C publication differs from frozen E/EV templates")
        guard = CodingBuilderSourceGuard(original, credential, self.reader, row.template, proof)
        self.forget_settled_lease(original.lease)  # actual EngineeringContext now owns it.
        return guard
