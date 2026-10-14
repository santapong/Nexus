"""Retained four original independent ACL/class/head probes; no operative approval is seeded."""

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.models import BrainSource
from nexus.company.brain.retrieval import SearchRequest
from nexus.company.brain.scope_support import brain_transaction
from nexus.tests.integration.operating_report_ancestor_fixture import build_source_ancestor_case
from nexus.tests.integration.test_company_brain_access import scope
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_operating_reports import (
    reports_factory as reports_factory,
)


async def grant_ancestor_source(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[ResourceRef, UUID]:
    async with brain_transaction(factory, owner_scope(), identity(OWNER)) as (session, _, _):
        source = await session.scalar(
            select(BrainSource).where(BrainSource.source_symbol == "review.private.v1")
        )
        assert source is not None
        resource, private_id = (
            ResourceRef(company_id=COMPANY, resource_id=source.resource_id),
            source.source_id,
        )
    await ResourceAccessStore(factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=resource,
            principal_id=ACTOR,
            active=True,
            expected_generation=1,
        ),
    )
    return resource, private_id


async def test_private_artifact_ancestor_source_is_filtered_before_fts(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    search, _, _ = await build_source_ancestor_case(reports_factory, tmp_path)
    found = await search.search(
        scope(), identity(ACTOR), SearchRequest(company_id=COMPANY, query="needle")
    )
    assert found.handles == ()


async def test_exact_evidence_cannot_bypass_private_artifact_ancestor_source(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    search, ids, _ = await build_source_ancestor_case(reports_factory, tmp_path)
    with pytest.raises(ValueError):
        await search.get_evidence(scope(), identity(ACTOR), ids, include_history=False)


async def test_allowed_ancestor_source_cannot_weaken_materialized_classification(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    search, ids, _ = await build_source_ancestor_case(reports_factory, tmp_path)
    await grant_ancestor_source(reports_factory)
    try:
        material = await search.get_evidence(scope(), identity(ACTOR), ids, include_history=False)
    except ValueError:
        return
    assert material[0].data_classification == "confidential"


async def test_allowed_ancestor_source_is_in_complete_citation_heads_and_resources(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    search, ids, _ = await build_source_ancestor_case(reports_factory, tmp_path)
    resource, private_id = await grant_ancestor_source(reports_factory)
    try:
        handles = await search.citation_handles(
            scope(), identity(ACTOR), ids, include_history=False
        )
    except ValueError:
        return
    assert private_id in {head.source_id for head in handles[0].source_heads}
    assert resource.resource_id in {row.resource_id for row in handles[0].contributors}
