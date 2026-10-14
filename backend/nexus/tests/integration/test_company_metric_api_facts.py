"""Actual HTTP projections remain permission-qualified after gateway lookup and saved history."""

import asyncio
import json
from pathlib import Path

import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.models import BrainResource
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.metric_contracts import (
    MetricObservationRecord,
    MetricObservationRequest,
)
from nexus.company.management.transactions import management_owner_transaction
from nexus.tests.integration.test_company_api import headers
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.integration.test_company_metric_api import BASE, observation_body
from nexus.tests.metric_api_support import configured_metric_api
from nexus.tests.metric_api_support import metric_api_factory as metric_api_factory
from nexus.tests.metric_fixture import accept_report


async def test_http_current_private_proof_is_unknown_and_dated_value_is_unavailable(
    metric_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app, case = await configured_metric_api(metric_api_factory, tmp_path)
    await accept_report(metric_api_factory, case)
    async with AsyncTestClient(app) as client:
        original = await client.post(BASE, json=observation_body(case), headers=headers(OWNER))
        assert (
            original.status_code == 200
            and original.json()["snapshot"]["comparison"]["value"]["value"] == 1
        )
        async with management_owner_transaction(metric_api_factory, control(), identity(OWNER)) as (
            session,
            _,
            _,
        ):
            resource = await session.get(BrainResource, (COMPANY, RESOURCE))
            assert resource is not None
            generation = resource.acl_generation
        await ResourceAccessStore(metric_api_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                principal_id=OWNER,
                active=False,
                expected_generation=generation,
            ),
        )
        before = await saved_m1(metric_api_factory)
        path = BASE + f"/{case.request.observation_id}"
        current = await client.get(path + "/current", headers=headers(OWNER))
        assert current.status_code == 200, current.text
        snapshot = current.json()["snapshot"]
        assert snapshot["comparison"]["value"]["kind"] == "unknown"
        assert "value" not in snapshot["comparison"]["value"]
        assert current.json()["comparison_result"] == "unknown"
        assert snapshot["sources"] == [] and snapshot["resources"] == []
        assert all(row["proof_ids"] == [] and row["artifacts"] == [] for row in snapshot["work"])
        assert (await client.get(path + "/recorded", headers=headers(OWNER))).status_code == 403
        assert await saved_m1(metric_api_factory) == before
        await asyncio.to_thread(
            (tmp_path / "metric-unknown-ui-fixture.json").write_text,
            json.dumps(
                {"scope": "synthetic revoked-source HTTP only", "current": current.json()}, indent=2
            ),
        )


async def test_owner_revoked_after_http_lookup_cannot_append_observation(
    metric_api_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, case = await configured_metric_api(metric_api_factory, tmp_path)
    original = case.store.observe

    async def revoke_then_observe(
        scope: CompanyControlScope, signed: VerifiedIdentity, request: MetricObservationRequest
    ) -> MetricObservationRecord:
        await PersistentCompanyDirectory(metric_api_factory).set_membership(
            MembershipChange(
                company_id=COMPANY, principal_id=OWNER, role="owner", membership_active=False
            ),
            control(),
        )
        return await original(scope, signed, request)

    monkeypatch.setattr(case.store, "observe", revoke_then_observe)
    before = await saved_m1(metric_api_factory)
    async with AsyncTestClient(app) as client:
        response = await client.post(BASE, json=observation_body(case), headers=headers(OWNER))
        assert response.status_code == 403, response.text
    assert await saved_m1(metric_api_factory) == before
