"""Real typed two-hop HTTP traversal stops at a private current ontology endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from litestar.testing import AsyncTestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.api_services import BrainServices
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.ontology import (
    GoalContent,
)
from nexus.company.brain.retrieval import CitationHandle
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.harness.journal_models import CompanyControl
from nexus.tests.brain_api_support import actual_services, brain_app, replace_source
from nexus.tests.brain_api_support import brain_api_factory as brain_api_factory
from nexus.tests.brain_graph_fixtures import DEPARTMENT, GOAL, ROOT
from nexus.tests.brain_graph_fixtures import DEPT_RESOURCE as DEPT_RESOURCE
from nexus.tests.brain_graph_fixtures import _endpoint_grant as _endpoint_grant
from nexus.tests.brain_graph_fixtures import _entity as _entity
from nexus.tests.brain_graph_fixtures import _graph_fixture as _graph_fixture
from nexus.tests.brain_graph_fixtures import _persist_entity as _persist_entity
from nexus.tests.integration.test_company_api import headers
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity

BASE = f"/api/v2/companies/{COMPANY}/brain"


async def test_current_entity_rejects_historical_support_after_actual_source_replacement(
    brain_api_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    services = await actual_services(brain_api_factory, tmp_path, b"R1 source supports the goal")
    async with AsyncTestClient(brain_app(services)) as client:
        found = await client.post(
            BASE + "/search", headers=headers(), json={"search": {"query": "supports"}}
        )
        handle = found.json()["handles"][0]["handle"]
        evidence_id = UUID(handle["evidence_id"])
        async with brain_api_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            await _endpoint_grant(session)
            await _persist_entity(
                session,
                _entity(GOAL, GoalContent(label="R1 derived goal"), DEPT_RESOURCE, evidence_id),
            )
        initial = await client.get(BASE + f"/entities/{GOAL}", headers=headers())
        assert initial.status_code == 200
        replaced = await replace_source(
            brain_api_factory,
            tmp_path,
            b"R2 withdraws goal support",
            UUID(handle["record"]["source"]["source_revision_id"]),
        )
        assert replaced.status == "accepted"
        denied = await client.get(BASE + f"/entities/{GOAL}", headers=headers())
        assert denied.status_code == 409 and "R1 derived goal" not in denied.text
        historical = await client.get(
            BASE + f"/evidence/{evidence_id}", params={"include_history": "true"}, headers=headers()
        )
        assert historical.status_code == 200 and historical.json()["source_state"] == "historical"


class SlowFinalEvidenceCheck(PersistentBrainRetriever):
    async def revalidate_handles(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        handles: tuple[CitationHandle, ...],
        now: datetime,
    ) -> None:
        await session.execute(select(func.pg_sleep(0.8)))
        await super().revalidate_handles(session, control, scope, identity, handles, now)


async def test_entity_own_grant_expiring_during_final_evidence_check_denies_http_payload(
    brain_api_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    services = await actual_services(brain_api_factory, tmp_path, b"bounded public evidence")
    async with AsyncTestClient(brain_app(services)) as client:
        found = await client.post(
            BASE + "/search", headers=headers(), json={"search": {"query": "bounded"}}
        )
        evidence_id = UUID(found.json()["handles"][0]["handle"]["evidence_id"])
        async with brain_api_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            await _endpoint_grant(session)
            await _persist_entity(
                session,
                _entity(
                    GOAL,
                    GoalContent(label="Expiry protected entity text"),
                    DEPT_RESOURCE,
                    evidence_id,
                ),
            )
            now: datetime | None = await session.scalar(select(func.clock_timestamp()))
        assert now is not None
        await ResourceAccessStore(brain_api_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=DEPT_RESOURCE),
                principal_id=ACTOR,
                active=True,
                expires_at=now + timedelta(seconds=0.5),
                expected_generation=1,
            ),
        )
        checked = BrainServices(
            services.directory,
            SlowFinalEvidenceCheck(
                brain_api_factory, services.retriever.blobs, limits=services.retriever.limits
            ),
            services.assembler,
        )
    async with AsyncTestClient(brain_app(checked)) as client:
        denied = await client.get(BASE + f"/entities/{GOAL}", headers=headers())
        assert denied.status_code == 403 and "Expiry protected entity text" not in denied.text


async def test_http_typed_two_hop_traversal_and_private_endpoint_denial(
    brain_api_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    raw = "".join("evidence " + letter * 8182 + "\n" for letter in "abc").encode()
    services = await actual_services(brain_api_factory, tmp_path, raw)
    async with AsyncTestClient(brain_app(services)) as client:
        found = await client.post(
            BASE + "/search", headers=headers(), json={"search": {"query": "evidence"}}
        )
        handles = found.json()["handles"]
        assert len(handles) >= 3
        evidence = tuple(UUID(row["handle"]["evidence_id"]) for row in handles)
        await _graph_fixture(brain_api_factory, evidence[:3])
        query = {"search": {"query": "nonexistentzzztoken", "entity_ids": [str(ROOT)]}}
        traversed = await client.post(BASE + "/search", headers=headers(), json=query)
        assert traversed.status_code == 200
        by_id = {row["handle"]["evidence_id"]: row for row in traversed.json()["handles"]}
        assert by_id[str(evidence[2])]["hop"] == 2
        assert by_id[str(evidence[2])]["match_kind"] == "relationship"
        await ResourceAccessStore(brain_api_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=DEPT_RESOURCE),
                principal_id=ACTOR,
                active=False,
                expires_at=None,
                expected_generation=1,
            ),
        )
        denied = await client.get(BASE + f"/entities/{DEPARTMENT}", headers=headers())
        assert denied.status_code == 403 and "Private department" not in denied.text
        limited = await client.post(BASE + "/search", headers=headers(), json=query)
        assert limited.status_code == 200 and limited.json()["handles"] == []
