"""Concrete locked native strategy input reads; supplied hashes never establish authority."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import BrainBlobStore
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ApprovalDecision
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_freshness import (
    RegisteredSourceFreshness,
    RegisteredSourcePolicies,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.generated_artifact_scope import require_generated_actor
from nexus.company.management.native_report_inputs import native_manifest
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.application_role import require_strategy_application_role
from nexus.company.strategy.artifact_contracts import StrategyArtifactRule
from nexus.company.strategy.artifact_identity import (
    require_strategy_action_payload,
)
from nexus.company.strategy.contracts import (
    STRATEGY_CHECK_CRITERIA,
    STRATEGY_CHECK_RECIPE,
    StrategyCheckInput,
)
from nexus.company.strategy.pair_reader import (
    require_current_strategy_author,
    resolve_strategy_pair_locked,
)
from nexus.company.strategy.producer_contracts import (
    StrategyProductionPolicy,
)
from nexus.company.strategy.publication_contracts import (
    PreparedStrategyPublication,
    StrategyPublicationRules,
)
from nexus.company.strategy.publication_intent import require_strategy_intent_locked
from nexus.company.strategy.publication_protection import (
    StrategyCheckMaterial as StrategyCheckMaterial,
)
from nexus.company.strategy.publication_protection import (
    StrategyProtectedPublication as StrategyProtectedPublication,
)
from nexus.company.strategy.publication_protection import (
    StrategyPublicationProtection,
    StrategyReadProtection,
    require_credential,
    strategy_publication_scope,
    target_grants_locked,
)
from nexus.company.strategy.publication_state import require_fresh_strategy_publication_state
from nexus.company.strategy.source_inputs import StrategySourceInputs
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import db_now, execution_row, lease_scope, require_lease
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction


class StrategyInputReader:
    """One server-owned policy/catalog/rule composition; no caller callback or owner shortcut."""

    def __init__(
        self,
        artifacts: BoundedArtifactReader,
        policies: RegisteredSourcePolicies,
        catalog: PlanAdmissionCatalog,
        production_policy: StrategyProductionPolicy,
        *,
        blobs: BrainBlobStore,
        write_rule: StrategyArtifactRule,
        check_rule: StrategyArtifactRule,
    ) -> None:
        require_acceptance(artifacts.blobs is blobs)
        self.artifacts, self.policies, self.blobs = artifacts, policies, blobs
        self.catalog = PlanAdmissionCatalog.model_validate(catalog.model_dump(warnings=False))
        self.production_policy = StrategyProductionPolicy.model_validate(
            production_policy.model_dump(warnings=False)
        )
        self.rules = StrategyPublicationRules(
            company_id=catalog.company_id,
            write=write_rule,
            check=check_rule,
            bundle_policy=policies.policy("generated.strategy-inputs.v2"),
            brief_policy=policies.policy(write_rule.source_policy),
            check_policy=policies.policy(check_rule.source_policy),
        )
        tools = {row.tool: row for row in self.catalog.tools}
        resources = {row.symbol: row.resource for row in self.catalog.resources}
        for rule in (self.rules.write, self.rules.check):
            configured = tools.get(rule.tool)
            require_acceptance(
                configured is not None
                and configured.tool_version == rule.tool_version
                and configured.resource == rule.resource_symbol
                and resources.get(rule.resource_symbol) == rule.target
            )
        require_acceptance(self.production_policy.company_id == self.catalog.company_id)
        self.sources = StrategySourceInputs(artifacts, policies)
        self.freshness = RegisteredSourceFreshness(artifacts.factory, policies)

    async def _read_gate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        prepared: PreparedStrategyPublication,
        credential: AuthenticatedWorkerIdentity,
    ) -> StrategyReadProtection:
        await require_strategy_application_role(session)
        require_credential(credential, identity, scope, await db_now(session))
        await require_brain_scope(session, control, scope, identity)
        require_acceptance(
            prepared.original.policy == self.production_policy
            and prepared.compiled.original_bundle.resource == self.rules.write.target
            and prepared.compiled.prepared.data_classification
            == self.rules.brief_policy.data_classification
        )
        for configured in (
            self.rules.bundle_policy,
            self.rules.brief_policy,
            self.rules.check_policy,
        ):
            require_acceptance(self.policies.policy(configured.source_symbol) == configured)
        pair = await resolve_strategy_pair_locked(session, control, prepared.original.snapshot)
        require_current_strategy_author(pair.author)
        sources = await self.sources.revalidate_locked(
            session, control, scope, identity, prepared.original.snapshot, credential=credential
        )
        manifest, classification = await native_manifest(
            session,
            scope,
            prepared.original.snapshot.inputs.artifacts,
            prepared.original.snapshot.inputs.contributors,
            prepared.original.snapshot.inputs.evidence,
            prepared.original.snapshot.inputs.required_resource_ids,
        )
        require_acceptance(manifest == prepared.compiled.prepared.inputs)
        levels = ("public", "internal", "confidential", "restricted")
        require_acceptance(
            levels.index(classification)
            <= levels.index(prepared.compiled.prepared.data_classification)
        )
        grants = await target_grants_locked(session, scope, prepared, self.rules)
        protection = StrategyReadProtection(sources, grants, pair, self.catalog)
        protection.require_time(await db_now(session))
        return protection

    async def revalidate_author_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action_id: UUID,
        prepared: PreparedStrategyPublication,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> StrategyPublicationProtection:
        """Check actual S issued action/fence, complete native input and late windows."""
        # This >50-line gate binds the actual intent, approval and full protected original material.
        await require_strategy_application_role(session)
        prepared = PreparedStrategyPublication.model_validate(prepared.model_dump(warnings=False))
        scope = strategy_publication_scope(lease, action_id)
        require_credential(credential, identity, scope, await db_now(session))
        require_acceptance(
            prepared.action_id == action_id
            and prepared.original.snapshot.scope.author.actor_id == lease.actor_id
        )
        work = await execution_row(session, lease_scope(lease))
        old = await session.scalar(
            select(BrainArtifactRevision.artifact_revision_id).where(
                BrainArtifactRevision.company_id == lease.company_id,
                BrainArtifactRevision.artifact_revision_id == prepared.brief.artifact_revision_id,
            )
        )
        action, _, _ = await require_generated_actor(
            session,
            control,
            work,
            lease,
            identity,
            action_id,
            self.catalog,
            self.artifacts,
            self.freshness,
            known=old is not None,
        )
        require_strategy_action_payload(action, self.rules.write, prepared.compiled.prepared)
        record = await session.get(JournalAction, action_id)
        require_acceptance(
            record is not None
            and record.approval_json is not None
            and record.consumed_at is not None
        )
        assert record is not None and record.approval_json is not None
        approval = ApprovalDecision.model_validate_json(record.approval_json)
        require_acceptance(
            approval.company_id == lease.company_id
            and approval.approver_id == control.owner_id
            and approval.decision == "approved"
            and approval.action_id == action_id
            and approval.action_hash == action_hash(action)
            and approval.action_revision == action.revision
        )
        effect = await require_strategy_intent_locked(session, work, action, record)
        require_acceptance(
            effect.intent_fence == lease.fence and effect.created_at <= await db_now(session)
        )
        require_fresh_strategy_publication_state(
            effect, exists=old is not None, output=prepared.brief, action_id=action_id
        )
        read = await self._read_gate(session, control, scope, identity, prepared, credential)
        require_acceptance(
            (lease.task_id, lease.trace_id, lease.run_id, lease.workspace_id)
            == (
                read.pair.author.task_id,
                read.pair.author.trace_id,
                read.pair.author.run_id,
                read.pair.author.workspace_id,
            )
        )
        protection = StrategyPublicationProtection(read, lease, approval)
        now = await db_now(session)
        require_lease(work, lease, now, execute=True)
        protection.require_time(now)
        return protection

    async def load_original_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        author_action_id: UUID,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> StrategyProtectedPublication:
        """Return actual original B/Brief and captured current protected windows."""
        from nexus.company.strategy.original_reader import load_strategy_original_locked

        return await load_strategy_original_locked(
            self, session, control, scope, identity, author_action_id, credential=credential
        )

    async def load_check_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        author_action_id: UUID,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> StrategyCheckMaterial:
        """Derive actual current SV target, original inputs and retained current windows."""
        # This >50-line target/manifest gate checks its retained protection after the last await.
        await require_strategy_application_role(session)
        scope = strategy_publication_scope(lease, author_action_id)
        work = await execution_row(session, lease_scope(lease))
        require_lease(work, lease, await db_now(session), execute=True)
        protected = await self.load_original_locked(
            session, control, scope, identity, author_action_id, credential=credential
        )
        loaded = protected.publication
        original = loaded.prepared.original.snapshot
        require_acceptance(
            (lease.actor_id, lease.task_id, lease.trace_id, lease.run_id, lease.workspace_id)
            == (
                original.scope.verifier.actor_id,
                original.scope.verifier.task_id,
                original.scope.verifier.trace_id,
                original.scope.verifier.run_id,
                original.scope.verifier.workspace_id,
            )
        )
        target = VerificationSpec(
            company_id=scope.company_id,
            author=original.scope.author,
            verifier=original.scope.verifier,
            action_id=author_action_id,
            proposal_sha256=loaded.receipt.proposal_hash,
            receipt_id=loaded.receipt.receipt_id,
            receipt_sha256=canonical_sha256(loaded.receipt),
            work_snapshot_sha256=original.scope.author_registration_sha256,
            criterion_ids=STRATEGY_CHECK_CRITERIA,
            artifacts=(loaded.prepared.brief,),
            check_recipe=STRATEGY_CHECK_RECIPE,
        )
        inputs, actual_class = await native_manifest(
            session,
            scope,
            (
                *original.inputs.artifacts,
                loaded.prepared.compiled.original_bundle.artifact,
                loaded.prepared.brief,
            ),
            original.inputs.contributors,
            original.inputs.evidence,
            original.inputs.required_resource_ids,
        )
        expected = {row.artifact_revision_id for row in original.inputs.artifacts} | {
            loaded.prepared.compiled.original_bundle.artifact.artifact_revision_id,
            loaded.prepared.brief.artifact_revision_id,
        }
        require_acceptance({row.artifact_revision_id for row in inputs.artifacts} == expected)
        levels = ("public", "internal", "confidential", "restricted")
        require_acceptance(
            levels.index(actual_class) <= levels.index(self.rules.check_policy.data_classification)
        )
        now = await db_now(session)
        require_lease(work, lease, now, execute=True)
        require_credential(credential, identity, scope, now)
        protected.protection.require_time(now)
        command = StrategyCheckInput(
            company_id=scope.company_id,
            target=target,
            output=loaded.prepared.brief,
            output_utf8=loaded.prepared.compiled.prepared.raw_bytes,
            snapshot=original,
        )
        return StrategyCheckMaterial(
            command, inputs, self.rules.check_policy.data_classification, protected.protection
        )

    async def protect_check_result_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        material: StrategyCheckMaterial,
        verifier_action_id: UUID,
        protected_result: ArtifactRevisionRef,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> StrategyReadProtection:
        """Revalidate current C bytes/full graph and preserve all first/current windows."""
        from nexus.company.strategy.result_reader import protect_strategy_check_result_locked

        return await protect_strategy_check_result_locked(
            self,
            session,
            control,
            lease,
            identity,
            material,
            verifier_action_id,
            protected_result,
            credential=credential,
        )
