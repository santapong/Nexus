"""First native generated target may be reviewed; hidden extra inputs never disclose parameters."""

from pathlib import Path
from uuid import uuid4

from litestar.testing import AsyncTestClient
from sqlalchemy import func, select

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.source_models import BrainArtifactRevision, BrainSource
from nexus.company.contracts.actions import ResourceRevision
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.tests.integration.test_company_api import headers
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_generated_review_support import generated_review_scenario
from nexus.tests.management_views_api_support import views_api_database as views_api_database
from nexus.tests.management_views_support import ViewsDatabase

BASE = f"/api/v2/companies/{COMPANY}/management"


async def test_empty_native_target_complete_citation_review_then_m1_decision(
    views_api_database: ViewsDatabase, tmp_path: Path
) -> None:
    scenario = await generated_review_scenario(views_api_database, tmp_path)
    async with views_api_database.admin() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(BrainArtifactRevision)
                .where(BrainArtifactRevision.resource_id == scenario.target)
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(BrainSource)
                .where(BrainSource.resource_id == scenario.target)
            )
            == 0
        )
    async with AsyncTestClient(scenario.app) as client:
        pinned = scenario.action.model_copy(
            update={
                "action_id": uuid4(),
                "preconditions": (
                    ResourceRevision(
                        resource=scenario.action.resource, revision="must-already-exist"
                    ),
                ),
            }
        )
        await CompanyJournal(views_api_database.app).submit(
            pinned,
            LedgerScope(
                company_id=COMPANY,
                principal_id=pinned.actor_id,
                task_id=pinned.task_id,
                trace_id=pinned.trace_id,
            ),
        )
        unavailable = await client.get(
            BASE + f"/actions/{pinned.action_id}/review", headers=headers(OWNER)
        )
        assert unavailable.status_code == 200 and unavailable.json()["detail"] is None
        assert unavailable.json()["availability"] == "unavailable"
        review = await client.get(
            BASE + f"/actions/{scenario.action.action_id}/review", headers=headers(OWNER)
        )
        assert review.status_code == 200 and review.json()["availability"] == "available", (
            review.text
        )
        detail = review.json()["detail"]
        assert detail["proposal"]["parameters"] == scenario.action.parameters
        decision = await client.post(
            f"/api/v2/companies/{COMPANY}/work/{scenario.action.task_id}/actions/{scenario.action.action_id}/decision",
            headers=headers(OWNER),
            json={
                "trace_id": detail["trace_id"],
                "expected_hash": detail["proposal_sha256"],
                "approved": True,
            },
        )
        assert decision.status_code == 200 and decision.json()["status"] == "decision_saved"
        # Revoke the citation outside the charter; public saved-report read alone is insufficient.
        async with views_api_database.admin() as session:
            resource = await session.get(BrainResource, (COMPANY, scenario.extra_resource))
            assert resource is not None
        await ResourceAccessStore(views_api_database.app).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=scenario.extra_resource),
                principal_id=OWNER,
                active=False,
                expected_generation=resource.acl_generation,
            ),
        )
        hidden = await client.get(
            BASE + f"/actions/{scenario.action.action_id}/review", headers=headers(OWNER)
        )
        assert hidden.status_code == 200 and hidden.json()["availability"] == "unavailable"
        assert hidden.json()["detail"] is None and "report_id" not in hidden.text
        assert "PRIVATE_EXTRA_CITATION" not in hidden.text
    async with views_api_database.admin() as session:
        assert await session.scalar(select(func.count()).select_from(SegmentDispatch)) == 0
        assert (
            await session.scalar(
                select(func.count())
                .select_from(BrainArtifactRevision)
                .where(BrainArtifactRevision.resource_id == scenario.target)
            )
            == 0
        )
