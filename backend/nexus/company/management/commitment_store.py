"""Owner CAS/history stores persist no execution, delivery or approval authority."""

from __future__ import annotations

from uuid import UUID, uuid5

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.base import Symbol
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.commitment_contracts import CommitmentRevision
from nexus.company.management.commitment_support import (
    commitment_record,
    require_commitment_binding,
)
from nexus.company.management.control_support import ManagementConflictError, db_clock, require_cas
from nexus.company.management.operation_models import (
    ManagementCommitmentHead,
    ManagementCommitmentRevision,
)
from nexus.company.management.operations import CommitmentDefinition
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.harness.journal_models import CompanyControl


class CommitmentStore:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def publish(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        definition: CommitmentDefinition,
        *,
        version: str,
        expected_revision_id: UUID | None,
    ) -> CommitmentRevision:
        definition = CommitmentDefinition.model_validate_json(definition.model_dump_json())
        version = TypeAdapter(Symbol).validate_python(version)
        async with management_owner_transaction(self.factory, scope, identity) as (
            session,
            control,
            _,
        ):
            existing = await session.scalar(
                select(ManagementCommitmentRevision).where(
                    ManagementCommitmentRevision.company_id == scope.company_id,
                    ManagementCommitmentRevision.commitment_id == definition.commitment_id,
                    ManagementCommitmentRevision.version == version,
                )
            )
            if existing is not None:
                record = commitment_record(existing)
                if record.definition != definition:
                    raise ManagementConflictError("Immutable commitment version cannot be rebound")
                return record
            await require_commitment_binding(session, control, scope, definition)
            return await _publish(
                session, control, scope, definition, version, expected_revision_id
            )

    async def current(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        commitment_id: UUID,
    ) -> CommitmentRevision:
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (
            session,
            _,
            _,
        ):
            head = await session.get(ManagementCommitmentHead, (scope.company_id, commitment_id))
            row = (
                await session.get(
                    ManagementCommitmentRevision, (scope.company_id, head.current_revision_id)
                )
                if head is not None
                else None
            )
            if row is None:
                raise ManagementDeniedError("Commitment is unavailable")
            return commitment_record(row)

    async def history(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        commitment_id: UUID,
        *,
        after_revision_id: UUID | None = None,
        limit: int = 32,
    ) -> tuple[CommitmentRevision, ...]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ManagementDeniedError("Commitment history page is invalid")
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (
            session,
            _,
            _,
        ):
            query = select(ManagementCommitmentRevision).where(
                ManagementCommitmentRevision.company_id == scope.company_id,
                ManagementCommitmentRevision.commitment_id == commitment_id,
            )
            if after_revision_id is not None:
                query = query.where(ManagementCommitmentRevision.revision_id > after_revision_id)
            return tuple(
                commitment_record(row)
                for row in (
                    await session.scalars(
                        query.order_by(ManagementCommitmentRevision.revision_id).limit(limit)
                    )
                ).all()
            )


async def _publish(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    definition: CommitmentDefinition,
    version: str,
    expected: UUID | None,
) -> CommitmentRevision:
    head = await session.get(ManagementCommitmentHead, (scope.company_id, definition.commitment_id))
    require_cas(head.current_revision_id if head else None, expected)
    if head is not None:
        old = await session.get(
            ManagementCommitmentRevision, (scope.company_id, head.current_revision_id)
        )
        if old is None or old.goal_id != definition.goal.goal_id:
            raise ManagementDeniedError("Logical commitment cannot change its goal")
    digest = canonical_sha256(definition)
    record = CommitmentRevision(
        company_id=scope.company_id,
        commitment_id=definition.commitment_id,
        revision_id=uuid5(definition.commitment_id, f"commitment:{version}:{digest}"),
        version=version,
        sha256=digest,
        definition=definition,
        recorded_by=control.owner_id,
        recorded_at=await db_clock(session),
    )
    session.add(_revision_row(record))
    await session.flush()
    if head is None:
        session.add(
            ManagementCommitmentHead(
                company_id=scope.company_id,
                commitment_id=definition.commitment_id,
                current_revision_id=record.revision_id,
            )
        )
    else:
        head.current_revision_id = record.revision_id
    await session.flush()
    return record


def _revision_row(record: CommitmentRevision) -> ManagementCommitmentRevision:
    definition = record.definition
    return ManagementCommitmentRevision(
        company_id=record.company_id,
        revision_id=record.revision_id,
        commitment_id=record.commitment_id,
        version=record.version,
        goal_id=definition.goal.goal_id,
        goal_revision_id=definition.goal.revision_id,
        plan_revision_id=definition.plan.plan_revision_id,
        responsible_id=definition.responsible_id,
        sha256=record.sha256,
        payload_json=definition.model_dump_json(),
        actionable_at=definition.due.actionable_at,
        recorded_by=record.recorded_by,
        recorded_at=record.recorded_at,
    )
