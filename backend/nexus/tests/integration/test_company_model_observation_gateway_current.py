"""Current post-intent native source/member/pause gates block SDK without refund or reissue."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest
from pydantic_ai.models import Model
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.company.control_store import CompanyControls
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.core.llm import company_adapters
from nexus.core.llm.company_adapter_contracts import ServerEndpoint
from nexus.core.llm.company_adapter_sdk import sdk_model
from nexus.core.llm.company_registry import ModelRegistration
from nexus.core.llm.company_wire_usage import WireObserver
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_models import CostHold
from nexus.harness.model_evidence import ModelEvidence
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.model_observation_gateway_fixture import (
    observed_gateway,
)
from nexus.tests.model_observation_gateway_fixture import (
    observed_gateway_factory as observed_gateway_factory,
)
from nexus.tests.unit.test_company_provider_conformance import response


@pytest.mark.parametrize("loss", ["source", "member", "pause"])
async def test_current_native_loss_after_intent_before_sdk_retains_unknown_hold_and_exact_attempt(
    observed_gateway_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    loss: str,
) -> None:
    wires: list[httpx2.Request] = []

    def handle(wire: httpx2.Request) -> httpx2.Response:
        wires.append(wire)
        return httpx2.Response(200, json=response("openai"))

    case = await observed_gateway(observed_gateway_factory, tmp_path, httpx2.MockTransport(handle))
    original_sdk = sdk_model
    reached = False

    @asynccontextmanager
    async def revoke_after_setup(
        model: ModelRegistration,
        endpoint: ServerEndpoint,
        observer: WireObserver,
    ) -> AsyncIterator[Model]:
        nonlocal reached
        async with original_sdk(model, endpoint, observer) as sdk:
            reached = True
            if loss == "pause":
                await CompanyControls(observed_gateway_factory).set_paused_registered(
                    control(), identity(OWNER), True
                )
            elif loss == "member":
                await PersistentCompanyDirectory(observed_gateway_factory).set_membership(
                    MembershipChange(
                        company_id=COMPANY,
                        principal_id=case.lease.actor_id,
                        role="member",
                        membership_active=False,
                    ),
                    control(),
                )
            else:
                async with observed_gateway_factory() as session, session.begin():
                    await session.execute(
                        select(func.set_config("nexus.company_id", str(COMPANY), True))
                    )
                    resource = await session.get(BrainResource, (COMPANY, RESOURCE))
                    assert resource is not None
                    generation = resource.acl_generation
                await ResourceAccessStore(observed_gateway_factory).change(
                    owner_scope(),
                    identity(OWNER),
                    ResourceAccessChange(
                        company_id=COMPANY,
                        resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                        principal_id=case.lease.actor_id,
                        active=False,
                        expected_generation=generation,
                    ),
                )
            yield sdk

    monkeypatch.setattr(company_adapters, "sdk_model", revoke_after_setup)
    result = await case.client.request_once(case.call, now=datetime.now(UTC))
    assert reached and not wires and result.provider_result.billing == "unknown"
    if loss == "member":
        assert result.recorded is None and result.ledger_billing == "unconfirmed"
        assert (
            result.recording_error == "recording_denied"
            and result.release_error == "release_denied"
        )
        path = (
            tmp_path
            / "evidence"
            / str(COMPANY)
            / str(case.call.action_id)
            / f"{case.call.request_id}.json"
        )
        saved = ModelEvidence.model_validate_json(path.read_bytes())
        saved.require_binding()
        assert saved.eligibility_provenance is not None and saved.result.billing == "unknown"
    else:
        assert result.recorded is not None and result.recorded.billing == "unknown", result
        assert (
            await case.evidence.load(result.recorded.artifact)
        ).eligibility_provenance is not None
    async with observed_gateway_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        work = await session.get(ExecutionWork, (COMPANY, case.call.task_id))
        intent = await session.get(EffectIntent, (COMPANY, case.call.action_id))
        hold = await session.get(CostHold, case.call.action_id)
        assert work and intent and hold
        assert work.model_requests_used == 1 and work.tool_attempts_used == 0
        assert intent.state == ("intent" if loss == "member" else "outcome_unknown")
        assert intent.receipt_json is None and hold.actual_usd is None
        assert hold.state == ("held" if loss == "member" else "unknown")
