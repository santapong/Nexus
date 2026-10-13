"""Owner-admitted measured goals use protected source proof without minting work allowance."""

from typing import Literal, Self
from uuid import UUID, uuid5

from pydantic import AwareDatetime, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.publication_evidence import PublicationEvidence, prepare_evidence
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_events import (
    GoalSubject,
    ManagementControlEvent,
    append_control_event,
    find_control_event,
)
from nexus.company.management.control_support import (
    ManagementConflictError,
    current_mandate,
    db_clock,
    require_cas,
    require_member,
)
from nexus.company.management.goals import GoalDefinition, GoalRevisionRef
from nexus.company.management.governance_models import (
    ManagementGoalEvidence,
    ManagementGoalHead,
    ManagementGoalRevision,
)
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.harness.journal_models import CompanyControl


class GoalRevisionRecord(GoalRevisionRef):
    """Owner publication read record, not independent metric satisfaction or work completion."""

    definition: GoalDefinition
    recorded_by: UUID
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def exact_definition(self) -> Self:
        if (self.company_id, self.goal_id) != (
            self.definition.company_id,
            self.definition.goal_id,
        ) or self.sha256 != canonical_sha256(self.definition):
            raise ValueError("Goal revision/hash differs from its exact measured definition")
        return self


def _record(row: ManagementGoalRevision) -> GoalRevisionRecord:
    return GoalRevisionRecord(
        company_id=row.company_id,
        goal_id=row.goal_id,
        revision_id=row.revision_id,
        version=row.version,
        sha256=row.sha256,
        definition=GoalDefinition.model_validate_json(row.payload_json),
        recorded_by=row.recorded_by,
        recorded_at=row.recorded_at,
    )


def _reference(record: GoalRevisionRecord) -> GoalRevisionRef:
    return GoalRevisionRef.model_validate_json(
        record.model_dump_json(include=set(GoalRevisionRef.model_fields))
    )


def _brain_scope(scope: CompanyControlScope, identity: VerifiedIdentity) -> BrainReadScope:
    return BrainReadScope(
        company_id=scope.company_id,
        workspace_id=identity.workspace_id,
        principal_id=scope.principal_id,
        operation_id=scope.operation_id,
        trace_id=scope.trace_id,
    )


async def _validate_goal(
    session: AsyncSession, control: CompanyControl, scope: CompanyControlScope, data: GoalDefinition
) -> None:
    if data.company_id != scope.company_id:
        raise ManagementDeniedError("Management goal scope is unavailable")
    mandate = await current_mandate(session, scope, data.mandate)
    if mandate.mandate.goals and data.goal_id not in mandate.mandate.goals:
        raise ManagementDeniedError("Goal is outside the current admitted mandate")
    await require_member(session, control, data.owner_id)


async def _recheck_evidence(
    retriever: PersistentBrainRetriever,
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    prepared: PublicationEvidence,
) -> None:
    now = await db_clock(session)
    await retriever.revalidate_handles(
        session, control, _brain_scope(scope, identity), identity, prepared.handles, now
    )
    now = await db_clock(session)
    expected = {row.resource_id: row for handle in prepared.handles for row in handle.contributors}
    current = {}
    ids = tuple(sorted(expected))
    for offset in range(0, len(ids), 32):
        fresh = await require_resources(
            session,
            _brain_scope(scope, identity),
            ids[offset : offset + 32],
            await db_clock(session),
        )
        current.update({row.resource_id: row for row in fresh})
    if current != expected:
        raise ManagementConflictError("Goal baseline contributor access changed")
    now = await db_clock(session)
    if any(row.expires_at is not None and row.expires_at <= now for row in current.values()):
        raise ManagementDeniedError("Goal baseline contributor access expired")
    for handle in prepared.handles:
        heads = {head.source_id: head for head in handle.source_heads}
        for reference in handle.source_contributors:
            head = heads[reference.source_id]
            if (
                head.current != reference
                or head.availability != "available"
                or (head.fresh_until is not None and head.fresh_until <= now)
            ):
                raise ManagementConflictError("Goal baseline source changed or is unavailable")


class GoalStore:
    def __init__(
        self, factory: async_sessionmaker[AsyncSession], retriever: PersistentBrainRetriever
    ) -> None:
        self.factory, self.retriever = factory, retriever

    async def publish(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        data: GoalDefinition,
        *,
        version: str,
        expected_revision_id: UUID | None,
    ) -> GoalRevisionRecord:
        data = GoalDefinition.model_validate_json(data.model_dump_json())
        async with management_owner_transaction(self.factory, scope, identity) as (
            session,
            control,
            _,
        ):
            await _validate_goal(session, control, scope, data)
        references = tuple(
            sorted(
                {ref for metric in data.metrics for ref in metric.baseline.evidence},
                key=lambda ref: ref.evidence_id,
            )
        )
        prepared = await prepare_evidence(
            self.retriever, _brain_scope(scope, identity), identity, references
        )
        async with management_owner_transaction(self.factory, scope, identity) as (
            session,
            control,
            _,
        ):
            await _validate_goal(session, control, scope, data)
            await _recheck_evidence(self.retriever, session, control, scope, identity, prepared)
            previous = await session.scalar(
                select(ManagementGoalRevision).where(
                    ManagementGoalRevision.company_id == scope.company_id,
                    ManagementGoalRevision.goal_id == data.goal_id,
                    ManagementGoalRevision.version == version,
                )
            )
            if previous is not None:
                record = _record(previous)
                if record.sha256 != canonical_sha256(data):
                    raise ManagementConflictError("Measured goal version cannot be rebound")
                return record
            head = await session.get(ManagementGoalHead, (scope.company_id, data.goal_id))
            require_cas(head.current_revision_id if head else None, expected_revision_id)
            old = (
                await session.get(
                    ManagementGoalRevision, (scope.company_id, head.current_revision_id)
                )
                if head
                else None
            )
            digest = canonical_sha256(data)
            now = await db_clock(session)
            record = GoalRevisionRecord(
                company_id=scope.company_id,
                goal_id=data.goal_id,
                revision_id=uuid5(data.goal_id, f"goal:{version}:{digest}"),
                version=version,
                sha256=digest,
                definition=data,
                recorded_by=control.owner_id,
                recorded_at=now,
            )
            session.add(
                ManagementGoalRevision(
                    company_id=scope.company_id,
                    goal_id=data.goal_id,
                    revision_id=record.revision_id,
                    version=version,
                    mandate_revision_id=data.mandate.revision_id,
                    responsible_id=data.owner_id,
                    sha256=digest,
                    payload_json=data.model_dump_json(),
                    actionable_at=data.due.actionable_at,
                    recorded_by=control.owner_id,
                    recorded_at=now,
                )
            )
            await session.flush()
            for metric in data.metrics:
                for evidence in metric.baseline.evidence:
                    session.add(
                        ManagementGoalEvidence(
                            company_id=scope.company_id,
                            goal_revision_id=record.revision_id,
                            metric_id=metric.metric_id,
                            evidence_id=evidence.evidence_id,
                        )
                    )
            if head is None:
                session.add(
                    ManagementGoalHead(
                        company_id=scope.company_id,
                        goal_id=data.goal_id,
                        current_revision_id=record.revision_id,
                        active=True,
                    )
                )
            else:
                head.current_revision_id = record.revision_id
            await session.flush()
            await append_control_event(
                session,
                scope,
                control,
                "publish",
                GoalSubject(
                    current=_reference(record), previous=_reference(_record(old)) if old else None
                ),
                await db_clock(session),
            )
            await _recheck_evidence(self.retriever, session, control, scope, identity, prepared)
            return record

    async def revoke(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, reference: GoalRevisionRef
    ) -> ManagementControlEvent:
        return await self._activity(scope, identity, reference, active=False)

    async def reactivate(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, reference: GoalRevisionRef
    ) -> ManagementControlEvent:
        async with management_owner_transaction(self.factory, scope, identity) as (
            session,
            control,
            _,
        ):
            data = await self._current(session, scope, reference)
            await _validate_goal(session, control, scope, data.definition)
        refs = tuple(
            sorted(
                {ref for metric in data.definition.metrics for ref in metric.baseline.evidence},
                key=lambda ref: ref.evidence_id,
            )
        )
        prepared = await prepare_evidence(
            self.retriever, _brain_scope(scope, identity), identity, refs
        )
        return await self._activity(scope, identity, reference, active=True, prepared=prepared)

    async def _activity(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        reference: GoalRevisionRef,
        *,
        active: bool,
        prepared: PublicationEvidence | None = None,
    ) -> ManagementControlEvent:
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=not active
        ) as (session, control, _):
            data = await self._current(session, scope, reference)
            subject = GoalSubject(current=_reference(data), previous=_reference(data))
            kind: Literal["reactivate", "revoke"] = "reactivate" if active else "revoke"
            old = await find_control_event(session, scope, kind, subject)
            if old is not None:
                return old
            if active:
                await _validate_goal(session, control, scope, data.definition)
                if prepared is None:
                    raise ManagementDeniedError("Goal reactivation requires current baseline proof")
                await _recheck_evidence(self.retriever, session, control, scope, identity, prepared)
            head = await session.get(ManagementGoalHead, (scope.company_id, data.goal_id))
            assert head is not None
            head.active = active
            await session.flush()
            result = await append_control_event(
                session, scope, control, kind, subject, await db_clock(session)
            )
            if prepared is not None:
                await _recheck_evidence(self.retriever, session, control, scope, identity, prepared)
            return result

    @staticmethod
    async def _current(
        session: AsyncSession, scope: CompanyControlScope, reference: GoalRevisionRef
    ) -> GoalRevisionRecord:
        head = await session.get(ManagementGoalHead, (scope.company_id, reference.goal_id))
        row = await session.get(ManagementGoalRevision, (scope.company_id, reference.revision_id))
        if (
            reference.company_id != scope.company_id
            or head is None
            or row is None
            or head.current_revision_id != reference.revision_id
        ):
            raise ManagementDeniedError("Current management goal is unavailable")
        record = _record(row)
        if _reference(record) != reference:
            raise ManagementDeniedError("Exact management goal is unavailable")
        return record
