"""Isolated exact-ID source/ACL fixture seeding through normal migrated restricted PG."""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import BrainBlobStore
from nexus.company.brain.models import BrainDerivation, BrainDerivationSource
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.directory_contracts import CompanyRegistration, MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import CompanyPolicy, LedgerScope
from nexus.tests.brain_catalog_fixtures import (
    AccessFixture,
    CompanyFixture,
    FixtureCatalog,
    fixture_catalog,
    fixture_id,
)
from nexus.tests.brain_seed_records import (
    artifact_row,
    resource_for,
    revision_row,
    seed_heads,
    seed_parse_evidence,
    source_row,
)
from nexus.tests.brain_source_fixtures import CaseSetup, SourcePack


def owner_read(company: CompanyFixture) -> tuple[BrainReadScope, VerifiedIdentity]:
    return BrainReadScope(
        company_id=company.company_id,
        workspace_id=company.workspace_id,
        principal_id=company.owner_id,
        operation_id=fixture_id("owner-operation", company.company_id),
        trace_id=fixture_id("owner-trace", company.company_id),
    ), VerifiedIdentity(principal_id=company.owner_id, workspace_id=company.workspace_id)


async def _directory(
    factory: async_sessionmaker[AsyncSession],
    catalog: FixtureCatalog,
) -> None:
    """Actual identity registration only; no sealed management projection is persisted."""
    directory, journal = PersistentCompanyDirectory(factory), CompanyJournal(factory)
    for company in catalog.companies:
        scope, _ = owner_read(company)
        control = CompanyControlScope(
            company_id=company.company_id,
            principal_id=company.owner_id,
            operation_id=scope.operation_id,
            trace_id=scope.trace_id,
        )
        await journal.create_company(
            CompanyPolicy(
                company_id=company.company_id,
                owner_id=company.owner_id,
                policy_version="fixture.policy.v1",
                price_version="fixture.prices.v1",
            ),
            LedgerScope(
                company_id=company.company_id,
                principal_id=company.owner_id,
                task_id=scope.operation_id,
                trace_id=scope.trace_id,
            ),
        )
        await directory.bootstrap(
            CompanyRegistration(
                company_id=company.company_id,
                workspace_id=company.workspace_id,
                owner_id=company.owner_id,
            ),
            control,
        )
        for member in catalog.principals:
            if member.company_id == company.company_id and member.principal_id != company.owner_id:
                await directory.set_membership(
                    MembershipChange(
                        company_id=company.company_id,
                        principal_id=member.principal_id,
                        role=member.role,
                    ),
                    control,
                )


async def seed_case(
    factory: async_sessionmaker[AsyncSession],
    blobs: BrainBlobStore,
    case_id: str,
) -> tuple[CaseSetup, SourcePack, FixtureCatalog]:
    """Caller supplies an empty normally migrated named DB; cases are not mixed together."""
    pack, catalog = await asyncio.to_thread(fixture_catalog)
    setup = next(row for row in pack.case_setup if row.case_id == case_id)
    await _directory(factory, catalog)
    artifacts = tuple(row for row in catalog.artifacts if row.case_id == case_id)
    for artifact in artifacts:
        await blobs.save(artifact.reference(), artifact.text.encode())
    for company in catalog.companies:
        scope, identity = owner_read(company)
        async with brain_transaction(factory, scope, identity, owner=True) as (session, _, _):
            await _resources(session, company.company_id, case_id, pack, catalog)
            selected = tuple(
                row
                for row in pack.source_revisions
                if (row.company_id, row.case_id) == (company.company_id, case_id)
            )
            seen: set[UUID] = set()
            for source in selected:
                if source.source_id not in seen:
                    session.add(source_row(source))
                    seen.add(source.source_id)
            await session.flush()
            targets = {row.artifact_id: row for row in artifacts}
            for artifact in artifacts:
                if artifact.company_id == company.company_id:
                    session.add(artifact_row(artifact, pack, catalog))
            await session.flush()
            for source in selected:
                session.add(revision_row(source, targets[source.artifact_id], pack, catalog))
            await session.flush()
            await _derivations(session, company.company_id, case_id, catalog)
            for source in selected:
                await seed_parse_evidence(session, source, targets[source.artifact_id], pack)
            await seed_heads(session, company.company_id, case_id, catalog)
    return setup, pack, catalog


async def _resources(
    session: AsyncSession,
    company_id: UUID,
    case_id: str,
    pack: SourcePack,
    catalog: FixtureCatalog,
) -> None:
    artifacts = tuple(
        row for row in catalog.artifacts if (row.company_id, row.case_id) == (company_id, case_id)
    )
    resources = {
        resource_for(row, pack): "source" if row.source_revision_id else "artifact"
        for row in artifacts
    }
    grants = tuple(
        row
        for row in catalog.access_grants
        if (row.company_id, row.case_id) == (company_id, case_id)
    )
    for key, kind in resources.items():
        generation = max((row.generation for row in grants if row.resource_id == key), default=1)
        session.add(
            BrainResource(
                company_id=company_id, resource_id=key, kind=kind, acl_generation=generation
            )
        )
    await session.flush()
    await _resource_grants(session, company_id, tuple(resources), grants, catalog)


async def _resource_grants(
    session: AsyncSession,
    company_id: UUID,
    resources: tuple[UUID, ...],
    grants: tuple[AccessFixture, ...],
    catalog: FixtureCatalog,
) -> None:
    for grant in grants:
        session.add(
            BrainResourceAccess(
                company_id=company_id,
                resource_id=grant.resource_id,
                principal_id=grant.principal_id,
                active=grant.active,
                generation=grant.generation,
                expires_at=grant.expires_at,
            )
        )
    source_resources = {row.resource_id for row in grants}
    # Explicit derivative target readers are fixture-only; contributor intersection still denies.
    for resource_id in set(resources) - source_resources:
        for principal in catalog.principals:
            if principal.company_id == company_id:
                session.add(
                    BrainResourceAccess(
                        company_id=company_id,
                        resource_id=resource_id,
                        principal_id=principal.principal_id,
                        active=True,
                        generation=1,
                    )
                )
    await session.flush()


async def _derivations(
    session: AsyncSession,
    company_id: UUID,
    case_id: str,
    catalog: FixtureCatalog,
) -> None:
    artifacts = {row.artifact_id: row for row in catalog.artifacts}
    selected = tuple(
        row for row in catalog.derivations if (row.company_id, row.case_id) == (company_id, case_id)
    )
    for row in selected:
        session.add(
            BrainDerivation(
                company_id=company_id,
                derivation_id=row.derivation_id,
                artifact_revision_id=artifacts[row.artifact_id].reference().artifact_revision_id,
                kind="chart" if row.kind == "chart_markup" else row.kind,
                recipe_version=row.recipe_version,
            )
        )
    await session.flush()
    for row in selected:
        for source_revision_id in row.contributing_source_revision_ids:
            session.add(
                BrainDerivationSource(
                    company_id=company_id,
                    derivation_id=row.derivation_id,
                    source_revision_id=source_revision_id,
                )
            )
    await session.flush()
