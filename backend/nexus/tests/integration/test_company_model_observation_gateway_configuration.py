"""Trusted client/gate/managed catalog must use one exact observation tuple before any intent."""

from pathlib import Path

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.model_authorizer import PersistentModelCallAuthorizer
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_model_authorizer import FixtureEstimator, recipe
from nexus.tests.model_observation_gateway_fixture import (
    observed_gateway,
)
from nexus.tests.model_observation_gateway_fixture import (
    observed_gateway_factory as observed_gateway_factory,
)


async def test_client_and_managed_gate_reject_mismatched_observation_before_intent(
    observed_gateway_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    def forbidden(wire: httpx2.Request) -> httpx2.Response:
        raise AssertionError("Configuration mismatch must not issue SDK")

    case = await observed_gateway(
        observed_gateway_factory, tmp_path, httpx2.MockTransport(forbidden)
    )
    wrong = case.observation.model_copy(update={"receipt_sha256": "7" * 64})
    with pytest.raises(ValueError, match="Client model eligibility"):
        case.gate.require_eligibility_configuration(case.registry, (wrong,))
    with pytest.raises(ValueError, match="Client model eligibility"):
        case.gate.require_eligibility_configuration(case.registry, ())
    with pytest.raises(ValueError, match="Managed model registry/observations"):
        PersistentModelCallAuthorizer(
            observed_gateway_factory,
            case.lease,
            identity(case.lease.actor_id),
            case.registry,
            resources=(),
            input_estimator=FixtureEstimator(),
            input_recipe=recipe(),
            allowed_classification="internal",
            evidence_store=case.evidence,
            management=case.management,
            model_observations=(wrong,),
        )
    async with observed_gateway_factory() as session, session.begin():
        await session.execute(
            select(func.set_config("nexus.company_id", str(case.call.company_id), True))
        )
        work = await session.get(ExecutionWork, (case.call.company_id, case.call.task_id))
        intent = await session.get(EffectIntent, (case.call.company_id, case.call.action_id))
        assert work is not None and work.model_requests_used == 0 and intent is None
