"""Native two-phase publication from server bytes and a current issued actor intent."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import BrainBlobStore
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_freshness import (
    RegisteredSourceFreshness,
    RegisteredSourcePolicies,
)
from nexus.company.management.generated_artifact_blob import prepare_generated_blob
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactPayload,
    GeneratedArtifactRule,
    GeneratedArtifactValidator,
)
from nexus.company.management.generated_artifact_identity import (
    generated_reference,
    require_action_payload,
)
from nexus.company.management.generated_artifact_privacy import GeneratedProtection, protect_inputs
from nexus.company.management.generated_artifact_rows import (
    require_generated_replay,
    write_generated_rows,
)
from nexus.company.management.generated_artifact_scope import (
    generated_scope,
    require_generated_actor,
)
from nexus.company.management.plan_support import PlanAdmissionCatalog, validate_plan_profile
from nexus.company.management.plans import ChildAllocation
from nexus.execution.runtime_contracts import ExecutionDeniedError, ExecutionLease
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)
from nexus.harness.journal_models import CompanyControl


class GeneratedArtifactPublisher:
    """Server-owned dependencies; no HTTP/model endpoint accepts raw output authority."""

    # This >50-line constructor keeps exact server tool/target/policy admissions
    # together; it performs no schema/grant/worker activation.
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        blobs: BrainBlobStore,
        catalog: PlanAdmissionCatalog,
        artifacts: BoundedArtifactReader,
        policies: RegisteredSourcePolicies,
        validator: GeneratedArtifactValidator,
        *,
        rules: tuple[GeneratedArtifactRule, ...],
    ) -> None:
        if (
            validator is None
            or policies is None
            or not 1 <= len(rules) <= 2
            or len({row.tool for row in rules}) != len(rules)
        ):
            raise ValueError(
                "Generated publication requires explicit trusted compiler/policies/fixed rules"
            )
        self.factory, self.blobs, self.artifacts, self.validator = (
            factory,
            blobs,
            artifacts,
            validator,
        )
        self.catalog = PlanAdmissionCatalog.model_validate_json(catalog.model_dump_json())
        self.freshness = RegisteredSourceFreshness(factory, policies)
        self.rules: dict[str, GeneratedArtifactRule] = {
            row.tool: GeneratedArtifactRule.model_validate_json(row.model_dump_json())
            for row in rules
        }
        self.policies = {
            row.tool: SourcePolicy.model_validate_json(
                policies.policy(row.source_policy).model_dump_json()
            )
            for row in self.rules.values()
        }
        resources = {row.symbol: row.resource for row in self.catalog.resources}
        tools = {row.tool: row for row in self.catalog.tools}
        for rule in self.rules.values():
            policy = self.policies[rule.tool]
            expected = (
                "generated.report.v1"
                if rule.tool == "company.report.write.v1"
                else "generated.check.v1"
            )
            permission = tools.get(rule.tool)
            if (
                rule.company_id != self.catalog.company_id
                or resources.get(rule.resource_symbol) != rule.target
                or permission is None
                or (permission.tool_version, permission.resource) != ("v1", rule.resource_symbol)
                or rule.source_policy != expected
                or policy.source_symbol != expected
                or policy.origin_kind != "derived"
                or policy.media_type != "application/json"
                or policy.data_classification == "public"
            ):
                raise ValueError(
                    "Generated fixed tool/target/policy is not admitted by server catalog"
                )

    # Keep the >50-line two-phase boundary adjacent: blob preparation is outside
    # both company transactions and final timing covers both prepared audiences.
    async def publish(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action_id: UUID,
        prepared: GeneratedArtifactPayload,
    ) -> ArtifactRevisionRef:
        """Current exact replay returns facts; metadata grants no acceptance or another call."""
        prepared = GeneratedArtifactPayload.model_validate_json(prepared.model_dump_json())
        reference = generated_reference(prepared, action_id)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            old = await session.get(
                BrainArtifactRevision, (lease.company_id, reference.artifact_revision_id)
            )
            initial, expiry, rule, child = await self._gate(
                session, control, lease, identity, action_id, prepared, known=old is not None
            )
            if old is not None:
                await require_generated_replay(
                    session, old, reference, prepared, rule, action_id, self.blobs.storage_symbol
                )
                self._time(initial, lease, expiry, child, await db_now(session))
                return reference
        await prepare_generated_blob(self.blobs, prepared, action_id)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            old = await session.get(
                BrainArtifactRevision, (lease.company_id, reference.artifact_revision_id)
            )
            current, expiry, rule, child = await self._gate(
                session, control, lease, identity, action_id, prepared, known=old is not None
            )
            if old is not None:
                await require_generated_replay(
                    session, old, reference, prepared, rule, action_id, self.blobs.storage_symbol
                )
            else:
                await write_generated_rows(
                    session,
                    generated_scope(lease, action_id),
                    reference,
                    prepared,
                    rule,
                    self.policies[rule.tool],
                    action_id,
                    self.blobs.storage_symbol,
                    await db_now(session),
                )
            # All awaited writes are done. Preserve both prepared audiences rather
            # than omitting a reader which expired since the first gate.
            work = await execution_row(session, lease_scope(lease))
            now = await db_now(session)
            require_lease(work, lease, now, execute=True)
            self._time(initial, lease, expiry, child, now)
            self._time(current, lease, expiry, child, now)
            return reference

    def _time(
        self,
        protection: GeneratedProtection,
        lease: ExecutionLease,
        expiry: datetime,
        child: ChildAllocation,
        now: datetime,
    ) -> None:
        if lease.expires_at <= now or expiry <= now:
            raise ExecutionDeniedError("Generated actor lease or exact authority expired")
        protection.require_time(now)
        validate_plan_profile(self.catalog, child, now)

    async def _gate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action_id: UUID,
        prepared: GeneratedArtifactPayload,
        *,
        known: bool,
    ) -> tuple[GeneratedProtection, datetime, GeneratedArtifactRule, ChildAllocation]:
        if prepared.company_id != lease.company_id:
            raise ExecutionDeniedError("Generated publication company is unavailable")
        work = await execution_row(session, lease_scope(lease))
        action, expiry, child = await require_generated_actor(
            session,
            control,
            work,
            lease,
            identity,
            action_id,
            self.catalog,
            self.artifacts,
            self.freshness,
            known=known,
        )
        rule = self.rules.get(action.tool)
        if rule is None:
            raise ExecutionDeniedError("Native generated action tool is unregistered")
        policy = self.policies[rule.tool]
        if (
            prepared.data_classification != policy.data_classification
            or len(prepared.raw_bytes) > policy.max_bytes
        ):
            raise ExecutionDeniedError(
                "Generated bytes/classification differ from fixed server policy"
            )
        require_action_payload(action, rule, prepared)
        scope = generated_scope(lease, action_id)
        await self.validator.revalidate(
            session, control, scope, identity, lease, action, prepared, await db_now(session)
        )
        protection = await protect_inputs(
            session, control, scope, identity, prepared, rule, self.artifacts, self.freshness
        )
        self._time(protection, lease, expiry, child, await db_now(session))
        return protection, expiry, rule, child
