"""Fixed private P/C configuration and process-local observations; never permissions."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Self
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from nexus.builder.engineering_bodies import CompleteEngineeringBody
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
from nexus.company.contracts.results import ActionReceipt
from nexus.company.cycle_artifacts.action_parameters import (
    CycleAuthorSelector,
    PresentationWriteParameters,
    SupportWriteParameters,
    decode_cycle_action,
)
from nexus.company.cycle_artifacts.check_contracts import (
    CycleArtifactCheckInput,
    cycle_check_snapshot,
)
from nexus.company.cycle_artifacts.checker import check_cycle_artifact
from nexus.company.cycle_artifacts.common import CycleKind, digest
from nexus.company.cycle_artifacts.native_contracts import CurrentEngineeringProof
from nexus.company.cycle_artifacts.production import PreparedCycleDeliverable
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_freshness import (
    QualifiedFreshness,
    RegisteredSourcePolicies,
    require_qualified_time,
)
from nexus.company.management.base import ManagementContract, ValueContract, require_company
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.cycle_admission_contracts import StockFlowCycleSlot
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.management.plan_admission_window import PlanGrantWindow, PlanSourceWindow
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.report_input_contracts import native_author
from nexus.core.llm.company_registry import DataClassification
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.standing_contracts import ToolPermission

CyclePhase = Literal["write", "check"]
CyclePart = Literal["json", "html", "markdown", "check"]


class CycleArtifactRule(ManagementContract):
    kind: CycleKind
    phase: CyclePhase
    permission: ToolPermission
    target: ResourceRef
    policies: tuple[SourcePolicy, ...]

    @property
    def tool(self) -> str:
        return self.permission.tool

    @property
    def tool_version(self) -> str:
        return self.permission.tool_version

    @property
    def resource_symbol(self) -> str:
        return self.permission.resource

    @property
    def recipe_version(self) -> str:
        return f"stockflow-{self.kind}-v1"

    @property
    def parts(self) -> tuple[CyclePart, ...]:
        return (
            ("check",)
            if self.phase == "check"
            else ("json", "html" if self.kind == "presentation" else "markdown")
        )

    def policy(self, part: CyclePart) -> SourcePolicy:
        require_acceptance(part in self.parts)
        return self.policies[self.parts.index(part)]

    @model_validator(mode="after")
    def fixed(self) -> Self:
        require_company(self.company_id, self.target)
        require_acceptance(
            (self.tool, self.tool_version) == (f"company.cycle-artifact.{self.phase}.v1", "v1")
            and len(self.policies) == len(self.parts)
        )
        media = {
            "json": "application/json",
            "check": "application/json",
            "html": "text/html",
            "markdown": "text/markdown",
        }
        for part, policy in zip(self.parts, self.policies, strict=True):
            SourcePolicy.model_validate(
                {key: getattr(policy, key) for key in SourcePolicy.model_fields}
            )
            require_acceptance(
                policy.source_symbol == f"generated.{self.kind}-{part}.v1"
                and policy.origin_kind == "derived"
                and policy.media_type == media[part]
                and 0 < policy.max_bytes <= 262144
                and policy.data_classification != "public"
            )
        require_acceptance(len({row.data_classification for row in self.policies}) == 1)
        return self


class CyclePublicationRules:
    def __init__(self, catalog: PlanAdmissionCatalog, policies: RegisteredSourcePolicies) -> None:
        self.catalog, self.policies = catalog, policies
        require_acceptance(catalog.cycle_admission is not None)
        tools = {row.tool: row for row in catalog.tools}
        resources = {row.symbol: row.resource for row in catalog.resources}
        kinds: tuple[CycleKind, ...] = ("presentation", "support")
        phases: tuple[CyclePhase, ...] = ("write", "check")
        self._rules = tuple(
            CycleArtifactRule(
                company_id=catalog.company_id,
                kind=kind,
                phase=phase,
                permission=tools[f"company.cycle-artifact.{phase}.v1"],
                target=resources[tools[f"company.cycle-artifact.{phase}.v1"].resource],
                policies=tuple(
                    policies.policy(f"generated.{kind}-{part}.v1")
                    for part in (
                        ("check",)
                        if phase == "check"
                        else ("json", "html" if kind == "presentation" else "markdown")
                    )
                ),
            )
            for kind in kinds
            for phase in phases
        )

    @property
    def write_target(self) -> ResourceRef:
        return self.rule("presentation", "write").target

    @property
    def check_target(self) -> ResourceRef:
        return self.rule("presentation", "check").target

    def rule(self, kind: CycleKind, phase: CyclePhase) -> CycleArtifactRule:
        matched = tuple(row for row in self._rules if (row.kind, row.phase) == (kind, phase))
        require_acceptance(len(matched) == 1)
        return matched[0]

    def slot(self, work: ExecutionWork) -> StockFlowCycleSlot:
        admission = self.catalog.cycle_admission
        require_acceptance(admission is not None)
        assert admission is not None
        bound, registration = native_author(work)
        slots = tuple(row for row in admission.slots[4:8] if row.child.binding == bound)
        require_acceptance(
            len(slots) == 1
            and registration.work == slots[0].work
            and registration.quota == slots[0].child.quota
        )
        return slots[0]

    def bind(self, work: ExecutionWork) -> CycleArtifactRule:
        role = self.slot(work).role
        kind: CycleKind = (
            "presentation" if role in {"presentation", "presentation_check"} else "support"
        )
        return self.rule(kind, "check" if role.endswith("_check") else "write")

    def fingerprint(self) -> tuple[object, ...]:
        for rule in self._rules:
            for configured in rule.policies:
                actual = self.policies.policy(configured.source_symbol)
                SourcePolicy.model_validate(
                    {key: getattr(actual, key) for key in SourcePolicy.model_fields}
                )
            require_acceptance(
                tuple(self.policies.policy(row.source_symbol) for row in rule.policies)
                == rule.policies
            )
        return canonical_sha256(self.catalog), tuple(canonical_sha256(row) for row in self._rules)


def check_reference(
    command: CycleArtifactCheckInput, action_id: UUID, raw: bytes
) -> ArtifactRevisionRef:
    key = uuid5(command.company_id, f"cycle-check:{command.artifact_kind}:{action_id}")
    return ArtifactRevisionRef(
        company_id=command.company_id,
        artifact_id=key,
        artifact_revision_id=uuid5(key, "revision:v1"),
        revision=f"stockflow-{command.artifact_kind}-check-v1",
        sha256=digest(raw),
        byte_length=len(raw),
    )


class PreparedCycleCheck(ValueContract):
    command: CycleArtifactCheckInput
    action_id: UUID
    raw_bytes: bytes = Field(min_length=1, max_length=262144)
    artifact: ArtifactRevisionRef
    classification: DataClassification

    @property
    def inputs(self) -> GeneratedArtifactInputs:
        return self.command.inputs

    @property
    def output_sha256(self) -> str:
        return self.artifact.sha256

    @property
    def input_snapshot_sha256(self) -> str:
        return canonical_sha256(cycle_check_snapshot(self.command))

    @property
    def input_manifest_sha256(self) -> str:
        return canonical_sha256(self.inputs)

    @model_validator(mode="after")
    def recomputed(self) -> Self:
        require_acceptance(
            self.action_id != self.command.target.action_id
            and self.classification != "public"
            and self.raw_bytes == check_cycle_artifact(self.command).model_dump_json().encode()
            and self.artifact == check_reference(self.command, self.action_id, self.raw_bytes)
        )
        return self


def prepare_cycle_check(
    command: CycleArtifactCheckInput, action_id: UUID, classification: DataClassification
) -> PreparedCycleCheck:
    raw = check_cycle_artifact(command).model_dump_json().encode()
    return PreparedCycleCheck(
        command=command,
        action_id=action_id,
        raw_bytes=raw,
        artifact=check_reference(command, action_id, raw),
        classification=classification,
    )


@dataclass(frozen=True, slots=True)
class CycleReadProtection:
    engineering: CurrentEngineeringProof
    grants: tuple[PlanGrantWindow, ...]
    freshness: tuple[QualifiedFreshness, ...]
    sources: tuple[PlanSourceWindow, ...]
    observed_at: datetime
    composition: tuple[object, ...]
    bodies: tuple[CompleteEngineeringBody, ...] = ()

    def require_time(self, now: datetime) -> None:
        require_acceptance(self.observed_at <= now)
        self.engineering.require_time(now)
        require_qualified_time(self.freshness, now)
        require_acceptance(
            all(row.expires_at is None or row.expires_at > now for row in self.grants)
        )
        for body in self.bodies:
            body.require_integrity()
            require_qualified_time(body.freshness, now)
            require_acceptance(
                all(
                    row.expires_at is None or row.expires_at > now
                    for row in body.first.contributors
                )
                and all(
                    row.availability == "available"
                    and (row.fresh_until is None or row.fresh_until > now)
                    for row in body.first.source_heads
                )
            )

    def require_same_scope(self, current: "CycleReadProtection") -> None:
        require_acceptance(
            self.grants == current.grants
            and self.sources == current.sources
            and self.freshness == current.freshness
        )


@dataclass(frozen=True, slots=True)
class CyclePublicationProtection:
    read: CycleReadProtection
    approval: ApprovalDecision
    lease: ExecutionLease

    def require_time(self, now: datetime) -> None:
        self.read.require_time(now)
        require_acceptance(
            self.read.engineering.initial.lease == self.lease
            and self.lease.expires_at > now
            and self.approval.issued_at <= now < self.approval.expires_at
        )


@dataclass(frozen=True, slots=True)
class CycleAuthorMaterial:
    prepared: PreparedCycleDeliverable
    engineering: CurrentEngineeringProof
    protection: CycleReadProtection


@dataclass(frozen=True, slots=True)
class CycleCheckMaterial:
    author: PreparedCycleDeliverable
    author_receipt: ActionReceipt
    command: CycleArtifactCheckInput
    prepared: PreparedCycleCheck
    engineering: CurrentEngineeringProof
    protection: CycleReadProtection


def require_author_action_pins(
    prepared: PreparedCycleDeliverable, action: ActionProposal, rule: CycleArtifactRule
) -> None:
    basis = prepared.basis
    write = rule
    pins = decode_cycle_action(
        action,
        expected_kind=rule.kind,
        phase="write",
        binding=basis.author,
        permission=write.permission,
    )
    require_acceptance(isinstance(pins, (PresentationWriteParameters, SupportWriteParameters)))
    assert isinstance(pins, (PresentationWriteParameters, SupportWriteParameters))
    selector = CycleAuthorSelector(
        company_id=basis.company_id,
        goal=basis.goal,
        producing_plan=basis.producing_plan,
        procedure_id=basis.procedure_id,
        author=basis.author,
        registration_sha256=basis.author_registration_sha256,
    )
    require_acceptance(
        pins.selector == selector
        and pins.output_manifest_sha256 == canonical_sha256(prepared.manifest)
        and pins.input_snapshot_sha256 == canonical_sha256(basis)
        and pins.input_manifest_sha256 == canonical_sha256(basis.inputs)
    )


def prepare_registered_cycle_check(
    command: CycleArtifactCheckInput, action_id: UUID, rule: CycleArtifactRule
) -> PreparedCycleCheck:
    """Compile under the actual check policy before an intent can reserve its attempt."""
    require_acceptance(rule.phase == "check" and command.artifact_kind == rule.kind)
    policy = rule.policy("check")
    prepared = prepare_cycle_check(command, action_id, policy.data_classification)
    require_acceptance(len(prepared.raw_bytes) <= policy.max_bytes)
    return prepared


def require_author_output_bounds(
    prepared: PreparedCycleDeliverable, rule: CycleArtifactRule
) -> None:
    """Check both registered private output caps before reserving an author tool attempt."""
    require_acceptance(rule.phase == "write" and rule.kind == prepared.basis.artifact_kind)
    for part, raw in zip(rule.parts, (prepared.typed_json, prepared.human_export), strict=True):
        require_acceptance(len(raw) <= rule.policy(part).max_bytes)
