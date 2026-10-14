"""One owner-saved occurrence prepares exact pending native actions without executing them."""

from typing import Literal
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import ReportCheckResult
from nexus.company.management.commitment_contracts import commitment_reference
from nexus.company.management.commitment_support import commitment_record
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactActionParameters,
    GeneratedArtifactPayload,
)
from nexus.company.management.generated_artifact_identity import require_action_payload
from nexus.company.management.native_profile_admission import admit_preparation, ledger_scope
from nexus.company.management.native_profile_compiler import recompute_pending
from nexus.company.management.native_profile_contracts import (
    NativeReportOperatingProfile,
    NativeReportPreparationPolicy,
    NativeReportPreparedAction,
    NativeReportProfileRef,
)
from nexus.company.management.native_profile_lookup import load_profile, report_record
from nexus.company.management.native_report_producer import NativeReportProducer
from nexus.company.management.operation_models import (
    ManagementCommitmentHead,
    ManagementCommitmentRevision,
)
from nexus.company.management.plan_support import PlanAdmissionCatalog, validate_plan_action
from nexus.company.management.plans import RunBinding
from nexus.company.management.scheduling_support import SchedulerIdentities, SchedulerResources
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import db_now, runtime_transaction
from nexus.harness.journal_submission import submit_pending_locked


class NativeReportPreparationService:
    """Configured actor resolver/compiler/catalog are live services, never portable permits."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        producer: NativeReportProducer,
        catalog: PlanAdmissionCatalog,
        artifacts: BoundedArtifactReader,
        freshness: RegisteredSourceFreshness,
        identities: SchedulerIdentities,
        resources: SchedulerResources,
        *,
        policy: NativeReportPreparationPolicy,
    ) -> None:
        self.factory, self.producer, self.artifacts, self.freshness = (
            factory,
            producer,
            artifacts,
            freshness,
        )
        self.catalog = PlanAdmissionCatalog.model_validate_json(catalog.model_dump_json())
        self.policy = NativeReportPreparationPolicy.model_validate_json(policy.model_dump_json())
        self.identities, self.resources = identities, resources
        named = {row.symbol: row.resource for row in self.catalog.resources}
        for rule in self.policy.rules:
            if (
                rule.company_id != self.catalog.company_id
                or named.get(rule.resource_symbol) != rule.target
            ):
                raise ValueError("Native preparation target differs from exact server catalog")

    async def resolve_profile(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        report_id: UUID,
        commitment_id: UUID,
        evidence_ids: tuple[UUID, ...],
    ) -> NativeReportOperatingProfile:
        """Resolve exact existing owner records to a descriptive, nonauthoritative selector."""
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (session, control, _):
            saved = await report_record(session, scope.company_id, report_id)
            head = await session.get(ManagementCommitmentHead, (scope.company_id, commitment_id))
            row = (
                await session.get(
                    ManagementCommitmentRevision, (scope.company_id, head.current_revision_id)
                )
                if head
                else None
            )
            if row is None:
                raise ManagementDeniedError("Native profile commitment is unavailable")
            reference = NativeReportProfileRef(
                company_id=scope.company_id,
                report_id=report_id,
                report_sha256=canonical_sha256(saved),
                selection_sha256=canonical_sha256(saved.selection),
                commitment=commitment_reference(commitment_record(row)),
                evidence_ids=evidence_ids,
            )
            profile, _ = await load_profile(
                session, control, scope, reference, require_due=False, now=await db_now(session)
            )
            return profile

    async def prepare_author(self, reference: NativeReportProfileRef) -> NativeReportPreparedAction:
        """Prepare one exact pending write with the configured actual author identity."""
        binding = await self._binding(reference, "author")
        identity = self._identity(binding)
        scope = self._scope(reference, binding, "author")
        prepared = await self.producer.prepare_report(
            scope, identity, reference.report_id, reference.evidence_ids
        )
        pins = GeneratedArtifactActionParameters(
            recipe_version=prepared.recipe_version,
            output_sha256=prepared.output_sha256,
            input_snapshot_sha256=prepared.input_snapshot_sha256,
            report_id=reference.report_id,
            evidence_ids=reference.evidence_ids,
        )
        return await self._append(
            reference, "author", binding, identity, scope, prepared, pins, None
        )

    async def prepare_verifier(
        self,
        reference: NativeReportProfileRef,
        lease: ExecutionLease,
        author_action_id: UUID,
    ) -> NativeReportPreparedAction:
        """Prepare one exact pending check using the selected verifier's actual lease."""
        binding = await self._binding(reference, "verifier")
        identity = self._identity(binding)
        if author_action_id != self._action_id(reference, "author"):
            raise ManagementDeniedError(
                "Verifier selector differs from the exact profile author action"
            )
        scope = self._scope(reference, binding, "verifier")
        prepared = await self.producer.prepare_check(lease, identity, author_action_id)
        result = ReportCheckResult.model_validate_json(prepared.raw_bytes)
        pins = GeneratedArtifactActionParameters(
            recipe_version=prepared.recipe_version,
            output_sha256=prepared.output_sha256,
            input_snapshot_sha256=prepared.input_snapshot_sha256,
            verification_target_sha256=result.target_sha256,
            author_action_id=author_action_id,
        )
        return await self._append(
            reference, "verifier", binding, identity, scope, prepared, pins, lease
        )

    async def _binding(
        self, reference: NativeReportProfileRef, phase: Literal["author", "verifier"]
    ) -> RunBinding:
        reference = NativeReportProfileRef.model_validate_json(reference.model_dump_json())
        if reference.company_id != self.catalog.company_id:
            raise ManagementDeniedError("Native profile company differs from configured catalog")
        async with self.factory() as session, session.begin():
            await session.execute(
                select(func.set_config("nexus.company_id", str(reference.company_id), True))
            )
            saved = await report_record(session, reference.company_id, reference.report_id)
            return saved.selection.author if phase == "author" else saved.selection.verifier

    def _identity(self, binding: RunBinding) -> VerifiedIdentity:
        identity = self.identities.actor(binding)
        if (identity.principal_id, identity.workspace_id) != (
            binding.actor_id,
            binding.workspace_id,
        ):
            raise ManagementDeniedError(
                "Configured native profile identity differs from actual actor"
            )
        return identity

    @staticmethod
    def _action_id(reference: NativeReportProfileRef, phase: str) -> UUID:
        return uuid5(reference.report_id, f"native-report-profile-v1:{phase}")

    def _scope(
        self, reference: NativeReportProfileRef, binding: RunBinding, phase: str
    ) -> BrainReadScope:
        return BrainReadScope(
            company_id=binding.company_id,
            workspace_id=binding.workspace_id,
            principal_id=binding.actor_id,
            operation_id=self._action_id(reference, phase),
            trace_id=binding.trace_id,
            task_id=binding.task_id,
            task_trace_id=binding.trace_id,
            actor_id=binding.actor_id,
        )

    async def _append(
        self,
        reference: NativeReportProfileRef,
        phase: Literal["author", "verifier"],
        binding: RunBinding,
        identity: VerifiedIdentity,
        scope: BrainReadScope,
        prepared: GeneratedArtifactPayload,
        pins: GeneratedArtifactActionParameters,
        lease: ExecutionLease | None,
    ) -> NativeReportPreparedAction:
        # Atomic >50-line preparation boundary: current native facts, exact pending
        # append and both final audience/profile clocks share CompanyControl.
        rule = next(
            row
            for row in self.policy.rules
            if row.tool
            == ("company.report.write.v1" if phase == "author" else "company.report.check.v1")
        )
        async with runtime_transaction(self.factory, ledger_scope(binding), identity) as (
            session,
            control,
            _,
        ):
            first = await admit_preparation(
                session,
                control,
                scope,
                identity,
                reference,
                phase,
                prepared,
                rule,
                self.catalog,
                self.artifacts,
                self.freshness,
                lease,
            )
            action = ActionProposal(
                company_id=binding.company_id,
                action_id=self._action_id(reference, phase),
                task_id=binding.task_id,
                trace_id=binding.trace_id,
                actor_id=binding.actor_id,
                revision=1,
                tool=rule.tool,
                tool_version=rule.tool_version,
                resource=rule.resource_symbol,
                parameters=pins.model_dump(mode="json", exclude_none=True),
                policy_version=control.policy_version,
                price_version=control.price_version,
                estimated_cost_usd=self.policy.estimated_cost_usd,
            )
            conditions = await self.resources.current(session, binding, action, identity)
            action = action.model_copy(update={"preconditions": conditions})
            require_action_payload(action, rule, prepared)
            validate_plan_action(
                self.catalog,
                first.child,
                first.charter,
                action,
                "tool_attempts",
                await db_now(session),
            )
            current = await recompute_pending(
                self.producer, session, control, scope, identity, lease, pins, prepared, phase
            )
            if current != prepared:
                raise ManagementDeniedError(
                    "Native profile compilation changed before pending append"
                )
            record = await submit_pending_locked(session, control, action, ledger_scope(binding))
            final = await admit_preparation(
                session,
                control,
                scope,
                identity,
                reference,
                phase,
                prepared,
                rule,
                self.catalog,
                self.artifacts,
                self.freshness,
                lease,
            )
            now = await db_now(session)
            first.require_time(self.catalog, now)
            final.require_time(self.catalog, now)
            return NativeReportPreparedAction(
                company_id=binding.company_id, profile=reference, phase=phase, action=record
            )
