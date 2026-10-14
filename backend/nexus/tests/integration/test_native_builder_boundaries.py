"""Current native source and complete recipient expiry prevent cached disclosure/publication."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.artifact_publisher import BuilderArtifactPublisher
from nexus.builder.execution_contracts import BuilderRunResult
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.claims import DerivationRecord
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.tests.builder_runtime_support import builder_factory as builder_factory
from nexus.tests.builder_runtime_support import scenario
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_plan_support import VERIFIER


async def change_source(
    factory: async_sessionmaker[AsyncSession],
    principal: UUID,
    *,
    active: bool,
    expires: datetime | None = None,
) -> None:
    async with brain_transaction(factory, owner_scope(), identity(OWNER), owner=True) as (
        session,
        _,
        _,
    ):
        row = await session.get(BrainResource, (COMPANY, RESOURCE))
        assert row is not None
        generation = row.acl_generation
    await ResourceAccessStore(factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            principal_id=principal,
            active=active,
            expected_generation=generation,
            expires_at=expires,
        ),
    )


async def test_saved_result_source_revocation_denies_disclosure_without_reissue(
    builder_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    item = await scenario(builder_factory, tmp_path)
    result = await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
    assert result is not None and result.outcome == "commands_succeeded"
    await change_source(builder_factory, ACTOR, active=False)
    assert (
        await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
        is None
    )
    assert await item.runner.results.load(item.spec) == result


async def test_recipient_input_expiry_during_append_rolls_back_publication(
    builder_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    item = await scenario(builder_factory, tmp_path)
    publisher = item.runner.publisher
    assert publisher is not None

    class ExpiringPublisher(BuilderArtifactPublisher):
        async def publish(
            self,
            result: BuilderRunResult,
            lease: ExecutionLease,
            identity_value: VerifiedIdentity,
            guard: BuilderSourceGuard,
        ) -> ArtifactRevisionRef:
            await change_source(
                builder_factory,
                VERIFIER,
                active=True,
                expires=datetime.now(UTC) + timedelta(seconds=0.6),
            )
            return await super().publish(result, lease, identity_value, guard)

        async def append(
            self,
            session: AsyncSession,
            result: BuilderRunResult,
            reference: ArtifactRevisionRef,
            derivation: DerivationRecord,
            originals: tuple[BrainArtifactRevision, ...],
            resources: tuple[UUID, ...],
        ) -> None:
            await super().append(session, result, reference, derivation, originals, resources)
            await session.execute(select(func.pg_sleep(0.8)))

    item.runner.publisher = ExpiringPublisher(
        builder_factory, publisher.blobs, publisher.target, publisher.policy
    )
    with pytest.raises(ValueError, match="expiry crossed publication"):
        await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
    result = await item.runner.results.load(item.spec)
    assert result is not None
    reference = publisher.reference(result)
    async with runtime_transaction(builder_factory, lease_scope(item.lease), identity(ACTOR)) as (
        session,
        _,
        _,
    ):
        assert (
            await session.get(BrainArtifactRevision, (COMPANY, reference.artifact_revision_id))
            is None
        )
        intent = await session.get(EffectIntent, (COMPANY, item.action.action_id))
        assert intent is not None and intent.state == "intent" and intent.receipt_json is None


async def test_actual_complete_log_cap_is_failed_and_stops_before_post(
    builder_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    item = await scenario(
        builder_factory, tmp_path, argv=("/bin/sh", "-c", "head -c 32768 /dev/zero")
    )
    result = await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
    assert result is not None and result.outcome == "resource_limited" and len(result.commands) == 1
    assert sum(row.metadata.byte_length for row in result.logs) == item.spec.job.limits.log_bytes
    assert not result.artifacts and "log_limit" in result.limitations


async def test_configured_publisher_missing_exact_target_denies_before_intent(
    builder_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    item = await scenario(builder_factory, tmp_path, output_in_descriptor=False)
    with pytest.raises(ValueError, match="exact output target before intent"):
        await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
    async with runtime_transaction(builder_factory, lease_scope(item.lease), identity(ACTOR)) as (
        session,
        _,
        _,
    ):
        assert (
            await session.get(EffectIntent, (item.lease.company_id, item.action.action_id)) is None
        )
        assert await session.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0


async def test_direct_reconcile_cannot_borrow_owner_guard_to_disclose_revoked_actor_source(
    builder_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await scenario(builder_factory, tmp_path)
    observed = await case.runner.run(
        case.lease, identity(ACTOR), case.action, case.spec, case.guard
    )
    assert observed is not None and observed.outcome == "commands_succeeded"
    await change_source(builder_factory, ACTOR, active=False)
    assert (
        await case.runner.run(case.lease, identity(ACTOR), case.action, case.spec, case.guard)
        is None
    )
    borrowed = BuilderSourceGuard(
        case.spec,
        case.guard.policy,
        case.guard.lease,
        identity(OWNER),
        case.guard.source,
        case.guard.artifacts,
        case.guard.freshness,
        case.guard.catalog,
    )
    try:
        result = await case.runner.reconcile(
            case.lease, identity(ACTOR), case.action, case.spec, borrowed
        )
    except ValueError:
        return
    assert result is None, (
        "Revoked actual actor must not disclose through another principal's guard"
    )
