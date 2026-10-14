"""Artifact-only generated ancestry retains every resource and source in report manifests.

Seeded edges are isolated reader/publisher conformance metadata, never work authority.
"""

from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.artifact_input_models import BrainArtifactInput, BrainArtifactResourceInput
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.artifact_target_store import ArtifactTargetStore
from nexus.company.management.operating_report_resources import report_resources
from nexus.tests.integration.management_acceptance_source_fixture import Policies, protected_text
from nexus.tests.integration.test_company_artifact_input_provenance import metadata_scenario
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_operating_reports import (
    reports_factory as reports_factory,
)
from nexus.tests.management_plan_support import VERIFIER


async def test_artifact_only_report_parent_extra_resource_and_source_cannot_drop_from_manifest(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await metadata_scenario(reports_factory, tmp_path)
    await PersistentCompanyDirectory(reports_factory).set_membership(
        MembershipChange(company_id=COMPANY, principal_id=VERIFIER, role="member"),
        control(),
    )
    extra = ResourceRef(company_id=COMPANY, resource_id=UUID(int=801))
    await ArtifactTargetStore(reports_factory).provision(
        owner_scope(), identity(OWNER), extra, readers=(OWNER,)
    )
    second = await protected_text(
        reports_factory,
        ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1"),
        Policies(),
        "Separate actual source behind artifact-only input.",
        400,
    )
    async with brain_transaction(reports_factory, owner_scope(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        session.add(
            BrainArtifactResourceInput(
                company_id=COMPANY,
                artifact_revision_id=case.parent.artifact_revision_id,
                resource_id=extra.resource_id,
            )
        )
        session.add(
            BrainArtifactInput(
                company_id=COMPANY,
                artifact_revision_id=case.parent.artifact_revision_id,
                input_artifact_revision_id=second.artifact_revision_id,
            )
        )
    async with brain_transaction(reports_factory, owner_scope(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        resources, _, heads = await report_resources(session, owner_scope(), (), (case.output,))
    assert {case.private.resource_id, extra.resource_id, UUID(int=401)} <= set(resources)
    assert UUID(int=400) in {row.source_id for row in heads}
