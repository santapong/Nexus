"""One current governed publication effect; issued history never re-enters a producer."""

from uuid import UUID, uuid5

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.cycle_artifacts.deliverable_store import CycleDeliverableStore
from nexus.company.cycle_artifacts.intent_check import CycleArtifactIntentCheck
from nexus.company.cycle_artifacts.publication_contracts import (
    CycleAuthorMaterial,
    CycleCheckMaterial,
)
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.application_role import require_strategy_application_role
from nexus.company.strategy.publication_protection import require_credential
from nexus.execution.effect_store import EffectStore
from nexus.execution.effect_support import effect_record
from nexus.execution.runtime_contracts import EffectRecord, ExecutionDeniedError, ExecutionLease
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)


class CycleArtifactEffects:
    """Trusted actual EffectStore/publisher composition; no invocation or retry callback."""

    def __init__(self, effects: EffectStore, publisher: CycleDeliverableStore) -> None:
        require_acceptance(
            type(effects) is EffectStore and type(publisher) is CycleDeliverableStore
        )
        self.effects, self.publisher = effects, publisher
        self.factory, self.catalog = publisher.factory, publisher.inputs.catalog
        self._bound = (effects, publisher, self.factory, self.catalog)
        self.composition()

    def composition(self) -> tuple[object, ...]:
        require_acceptance(
            all(
                a is b
                for a, b in zip(
                    (self.effects, self.publisher, self.factory, self.catalog),
                    self._bound,
                    strict=True,
                )
            )
            and self.effects._factory is self.factory
            and self.effects._management_catalog is self.catalog
            and self.effects._management_artifacts is self.publisher.inputs.artifacts
            and self.effects._management_freshness is self.publisher.inputs.freshness
        )
        return (*self._bound, self.publisher.composition())

    def require_composition(self, original: tuple[object, ...]) -> None:
        require_acceptance(self.composition() == original)
        self.publisher.require_composition(original[-1])  # type: ignore[arg-type]

    async def known(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action_id: UUID,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> EffectRecord | None:
        """Own-fence metadata only, including while paused/inactive or input READ has expired."""
        original = self.composition()
        scope = self.publisher.inputs.scope(lease, identity, action_id)
        async with runtime_transaction(
            self.factory, lease_scope(lease), identity, allow_paused=True, allow_inactive=True
        ) as (session, _, _):
            await require_strategy_application_role(session)
            work = await execution_row(session, lease_scope(lease))
            require_lease(work, lease, await db_now(session))
            self.publisher.inputs.rules.bind(work)
            require_credential(credential, identity, scope, await db_now(session))
            row = await session.get(EffectIntent, (lease.company_id, action_id))
            if row is not None:
                require_acceptance(
                    (
                        row.company_id,
                        row.task_id,
                        row.trace_id,
                        row.run_id,
                        row.action_id,
                        row.attempt_kind,
                    )
                    == (
                        lease.company_id,
                        lease.task_id,
                        lease.trace_id,
                        lease.run_id,
                        action_id,
                        "tool_attempts",
                    )
                    and type(row.intent_fence) is int
                    and 0 < row.intent_fence <= work.fence
                )
            final = await db_now(session)
            self.require_composition(original)
            require_lease(work, lease, final)
            require_credential(credential, identity, scope, final)
            return effect_record(row) if row is not None else None

    async def _run(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action_id: UUID,
        material: CycleAuthorMaterial | CycleCheckMaterial,
        credential: AuthenticatedWorkerIdentity,
    ) -> EffectRecord:
        """Publish only after an actual committed call permit; lost outcome stays unresolved."""
        original = self.composition()
        reader = (
            self.publisher.inputs
            if isinstance(material, CycleAuthorMaterial)
            else self.publisher.originals
        )
        require_acceptance(material.prepared.action_id == action_id)
        guard = CycleArtifactIntentCheck(
            reader, lease, identity, action_id, material, credential=credential
        )
        start = await self.effects.begin(lease, identity, action_id, before_intent=guard)
        self.require_composition(original)
        if not start.permit_external_call:
            return start.record
        # No catch/retry or success fabrication: a crash after publication leaves the committed
        # intent unresolved for the existing recovery protocol and preserves its positive hold.
        if isinstance(material, CycleAuthorMaterial):
            output = await self.publisher.publish_author(
                lease, identity, material, credential=credential
            )
            require_acceptance(output == material.prepared.manifest)
            refs = tuple(row.artifact for row in output.parts)
        else:
            reference = await self.publisher.publish_check(
                lease, identity, material, credential=credential
            )
            require_acceptance(reference == material.prepared.artifact)
            refs = (reference,)
        self.require_composition(original)
        async with runtime_transaction(
            self.factory, lease_scope(lease), identity, allow_paused=True, allow_inactive=True
        ) as (session, _, _):
            work = await execution_row(session, lease_scope(lease))
            now = await db_now(session)
            require_lease(work, lease, now)
            require_credential(credential, identity, reader.scope(lease, identity, action_id), now)
        self.require_composition(original)
        receipt = ActionReceipt(
            company_id=lease.company_id,
            receipt_id=uuid5(action_id, "cycle-deliverable-receipt:v1"),
            action_id=action_id,
            task_id=lease.task_id,
            trace_id=lease.trace_id,
            proposal_hash=start.record.proposal_hash,
            outcome="succeeded",
            recorded_at=now,
            artifacts=tuple(
                ArtifactRef(
                    company_id=ref.company_id,
                    artifact_id=ref.artifact_id,
                    revision=ref.revision,
                    sha256=ref.sha256,
                    reference=f"brain-artifact:{ref.artifact_revision_id}",
                )
                for ref in refs
            ),
        )
        # Unknown native billing remains held; this compiler invents neither a price nor refund.
        return await self.effects.record_receipt(lease, identity, receipt, actual_usd=None)

    async def run_author(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action_id: UUID,
        material: CycleAuthorMaterial | None,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> EffectRecord:
        """Repeat the metadata probe before requiring original retained author material."""
        known = await self.known(lease, identity, action_id, credential=credential)
        if known is not None:
            return known
        if material is None:
            raise ExecutionDeniedError(
                "Unissued cycle action requires its original retained preparation"
            )
        require_acceptance(type(material) is CycleAuthorMaterial)
        return await self._run(lease, identity, action_id, material, credential)

    async def run_check(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action_id: UUID,
        material: CycleCheckMaterial | None,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> EffectRecord:
        """Known checker history returns without producer, publisher, attempt or proof mutation."""
        known = await self.known(lease, identity, action_id, credential=credential)
        if known is not None:
            return known
        if material is None:
            raise ExecutionDeniedError(
                "Unissued cycle action requires its original retained preparation"
            )
        require_acceptance(type(material) is CycleCheckMaterial)
        return await self._run(lease, identity, action_id, material, credential)

    async def observe_current_outputs(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        material: CycleAuthorMaterial | CycleCheckMaterial,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> None:
        """Current READ is separate from immutable issued history; no publication or effect."""
        original = self.composition()
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            work = await execution_row(session, lease_scope(lease))
            if isinstance(material, CycleAuthorMaterial):
                current = await self.publisher.inputs.revalidate_author_locked(
                    session, control, work, lease, identity, material, credential=credential
                )
            else:
                current = await self.publisher.originals.revalidate_check_locked(
                    session, control, work, lease, identity, material, credential=credential
                )
            await self.publisher._replay(session, control, lease, identity, material)
            final = await db_now(session)
            self.require_composition(original)
            require_lease(work, lease, final, execute=True)
            credential.require_time(final)
            material.protection.require_time(final)
            current.require_time(final)
