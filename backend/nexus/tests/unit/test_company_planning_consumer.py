"""Real client/SDK MockTransport; native claim/record/release delivery is explicitly mocked.

These finite tests are not PostgreSQL gate, live provider, or planner activation evidence.
The >400-line exception keeps the actual two-SDK fixture, protected evidence and
interpretation/cancellation matrix adjacent, without a separate fixture framework.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid5

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.context import ContextLimits
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.interfaces import ContextAuthorityProvider
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plan_support import PlanSourceFreshness
from nexus.company.management.planning_consumer import RegisteredPlanningConsumer
from nexus.company.management.planning_content import PlanningContent
from nexus.company.management.planning_intent import (
    PreparedPlanningRequest,
    prepare_planning_request,
)
from nexus.core.llm.company_adapter_contracts import (
    AuthorizedModelAttempt,
    CompanyModelRequest,
    CompanyModelResult,
    ServerEndpoint,
    request_hash,
)
from nexus.core.llm.company_pricing import CostQuote, TokenBounds, TokenUsage, reconcile_cost
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import lease_scope
from nexus.harness.model_authorizer import PersistentModelCallAuthorizer, RecordedModelOutcome
from nexus.harness.model_client import GovernedModelClient
from nexus.harness.model_client_contracts import GovernedModelCancelledError, GovernedModelResult
from nexus.harness.model_evidence import FileModelEvidenceStore, ModelEvidence
from nexus.tests.integration.test_company_model_authorizer import FixtureEstimator
from nexus.tests.unit.test_company_planning_content import content
from nexus.tests.unit.test_company_planning_intent import prepared_inputs
from nexus.tests.unit.test_company_provider_conformance import EndpointResolver, catalog, response


def composition(
    tmp_path: Path,
    transport: httpx2.AsyncBaseTransport,
    provider: str = "openai",
    *,
    timeout_seconds: float = 1,
) -> tuple[RegisteredPlanningConsumer, PreparedPlanningRequest]:
    call, context, binding, scope, recipe, lease = prepared_inputs()
    registry = planning_registry(provider)
    call = call.model_copy(
        update={"bounds": TokenBounds(input_tokens=28000, max_output_tokens=256)}
    )
    prepared = prepare_planning_request(call, context, binding, scope=scope, input_recipe=recipe)
    factory = async_sessionmaker[AsyncSession]()
    contexts = PersistentContextAssembler(
        factory,
        cast(PersistentBrainRetriever, object()),
        cast(ContextAuthorityProvider, object()),
        limits=ContextLimits(policy_version="context-v1"),
    )
    endpoint = ServerEndpoint(
        endpoint_id="fixture-endpoint",
        provider=provider,
        api_family="openai_responses" if provider == "openai" else "google_generate_content",
        base_url="https://offline.invalid/v1",
        api_key=SecretStr("fake-test-key"),
        transport=transport,
        timeout_seconds=timeout_seconds,
    )
    management = ManagementExecutionServices(
        PlanAdmissionCatalog(
            company_id=call.company_id,
            models=registry,
            admitted_profiles=frozenset({"engineering"}),
            check_recipes=frozenset(),
        ),
        cast(BoundedArtifactReader, object()),
        cast(PlanSourceFreshness, object()),
    )
    consumer = RegisteredPlanningConsumer(
        factory,
        registry,
        EndpointResolver(endpoint),
        management,
        contexts,
        FileModelEvidenceStore(tmp_path / "evidence"),
        FixtureEstimator(),
        recipe,
        lease,
        VerifiedIdentity(principal_id=lease.actor_id, workspace_id=lease.workspace_id),
        resources=(),
        allowed_classification="confidential",
    )
    return consumer, prepared


def planning_registry(provider: str) -> ModelRegistry:
    registry = catalog(provider)
    return registry.model_copy(
        update={
            "models": (
                registry.models[0].model_copy(
                    update={
                        "allowed_data": frozenset({"internal", "confidential"}),
                        "context_window": 30000,
                    }
                ),
            )
        }
    )


@pytest.mark.parametrize("provider", ["openai", "google"])
@pytest.mark.parametrize("semantic", ["valid", "cycle", "foreign", "delayed"])
async def test_actual_sdk_single_post_and_recorded_file_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str, semantic: str
) -> None:
    import json

    calls = []
    release_wire = asyncio.Event()
    emitted = content()
    tasks = emitted["tasks"]
    assert isinstance(tasks, list)
    tasks[0]["evidence_ids"] = [str(prepared_inputs()[1].manifest.inclusions[0].handle.evidence_id)]
    if semantic == "cycle":
        tasks[0]["depends_on"] = [tasks[0]["key"]]
    elif semantic == "foreign":
        tasks[0]["evidence_ids"] = ["00000000-0000-0000-0000-000000000999"]

    async def wire(call: httpx2.Request) -> httpx2.Response:
        calls.append(call.method)
        if semantic == "delayed":
            await release_wire.wait()
        assert prepared.request.output_schema is not None
        expected_comment = json.loads(prepared.request.output_schema.document)["$comment"]
        # This assertion covers the actual pinned SDK's emitted JSON, not a fake client.
        assert expected_comment in comments(json.loads(call.content))
        document = response(provider)
        if provider == "openai":
            document["output"] = [
                {
                    "id": "m",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": json.dumps(emitted), "annotations": []}
                    ],
                }
            ]
        else:
            document["candidates"] = [
                {
                    "content": {"role": "model", "parts": [{"text": json.dumps(emitted)}]},
                    "finishReason": "STOP",
                    "index": 0,
                }
            ]
        return httpx2.Response(200, json=document)

    consumer, prepared = composition(
        tmp_path,
        httpx2.MockTransport(wire),
        provider,
        timeout_seconds=1 if semantic == "delayed" else 30,
    )

    async def claim(
        gate: PersistentModelCallAuthorizer, call: CompanyModelRequest, quote: CostQuote
    ) -> AuthorizedModelAttempt:
        return AuthorizedModelAttempt(
            scope=lease_scope(consumer.lease),
            action_id=call.action_id,
            attempt_id=call.attempt_id,
            request_id=call.request_id,
            request_hash=request_hash(call),
            registry_id=call.registry_id,
            registry_revision=call.registry_revision,
            price_version=call.price_version,
            reserved_usd=quote.amount_usd,
        )

    async def before(
        gate: PersistentModelCallAuthorizer,
        call: CompanyModelRequest,
        quote: CostQuote,
        provenance: str | None,
    ) -> datetime:
        return datetime.now(UTC)

    async def record(
        gate: PersistentModelCallAuthorizer, call: CompanyModelRequest, result: CompanyModelResult
    ) -> RecordedModelOutcome:
        envelope = ModelEvidence(
            request=call,
            request_hash=request_hash(call),
            action_hash="a" * 64,
            model=planning_registry(provider).models[0],
            registry_revision=call.registry_revision,
            price_version=call.price_version,
            recipe=prepared.input_recipe,
            input_estimate=FixtureEstimator().estimate(
                call, planning_registry(provider), prepared.input_recipe
            ),
            result=result,
            source_event_at=datetime.now(UTC),
            checked_at=datetime.now(UTC),
            owner_id=call.actor_id,
        )
        artifact = await consumer.evidence.save(envelope)
        if result.billing == "unknown":
            return RecordedModelOutcome(artifact=artifact, billing="unknown", stop_required=True)
        assert result.billing == "known" and result.usage is not None
        actual = reconcile_cost(envelope.model.price, result.usage, now=envelope.source_event_at)
        return RecordedModelOutcome(
            artifact=artifact,
            billing="known",
            actual_usd=actual.amount_usd,
            stop_required=(
                result.status != "response"
                or result.usage.input_tokens > call.bounds.input_tokens
                or result.usage.output_tokens > call.bounds.max_output_tokens
            ),
            receipt_id=uuid5(call.action_id, "model-receipt-v1"),
        )

    monkeypatch.setattr(PersistentModelCallAuthorizer, "claim", claim)
    monkeypatch.setattr(PersistentModelCallAuthorizer, "revalidate_before_sdk", before)
    monkeypatch.setattr(PersistentModelCallAuthorizer, "record_result", record)
    from types import SimpleNamespace

    execution = ExecutionStore(async_sessionmaker[AsyncSession]())
    release = AsyncMock(return_value=SimpleNamespace(state="verifying"))
    monkeypatch.setattr(execution, "release", release)
    monkeypatch.setattr(
        ManagementExecutionServices, "execution_store", lambda self, factory: execution
    )
    try:
        outcome = await consumer.request_once(prepared, now=datetime.now(UTC))
    finally:
        release_wire.set()
        pending = consumer.pending_owners()
        if pending:
            _, remaining = await asyncio.wait(pending, timeout=5)
            assert not remaining
    if semantic == "delayed":
        assert calls == ["POST"]
        assert outcome.candidate is None and outcome.denial == "model_outcome"
        assert outcome.governed.provider_result.billing == "unknown"
        assert outcome.governed.provider_result.error_code == "sdk_resources_unresolved"
        assert outcome.governed.recorded is not None
        assert outcome.governed.recorded.billing == "unknown"
        assert outcome.governed.recorded.actual_usd is None
        assert outcome.governed.recorded.receipt_id is None
        assert outcome.governed.stop_required
        assert outcome.governed.release_status == "failed"
        release.assert_not_awaited()
        saved = await consumer.evidence.load(outcome.governed.recorded.artifact)
        assert saved.result == outcome.governed.provider_result
        with pytest.raises(ValueError, match="one planning request"):
            await consumer.request_once(prepared, now=datetime.now(UTC))
        assert calls == ["POST"]
        return
    assert outcome.governed.recorded is not None
    assert outcome.governed.ledger_billing == "known" and not outcome.governed.stop_required
    assert outcome.governed.release_status == "released"
    assert not outcome.company_completed
    stored = await consumer.evidence.load(outcome.governed.recorded.artifact)
    assert stored.request.output_schema == prepared.request.output_schema
    assert stored.request.output_schema is not None
    annotation = json.loads(json.loads(stored.request.output_schema.document)["$comment"])
    assert annotation["version"] == "nexus.company.planning-binding.v2"
    assert annotation["sha256"] == canonical_sha256(prepared.binding)
    assert annotation["binding"] == prepared.binding.model_dump(mode="json")
    if semantic == "valid":
        assert outcome.candidate is not None, outcome.denial
        assert outcome.candidate.status == "historical_candidate"
        assert outcome.candidate.binding == prepared.binding
        assert outcome.candidate.content == PlanningContent.model_validate_json(json.dumps(emitted))
        assert not outcome.stop_required
    else:
        assert outcome.candidate is None and outcome.denial == "invalid_content"
        assert outcome.stop_required
    assert calls == ["POST"]
    release.assert_awaited_once()
    with pytest.raises(ValueError, match="one planning request"):
        await consumer.request_once(prepared, now=datetime.now(UTC))
    assert calls == ["POST"]


def comments(value: object) -> list[str]:
    if isinstance(value, dict):
        return ([value["$comment"]] if "$comment" in value else []) + [
            comment for child in value.values() for comment in comments(child)
        ]
    if isinstance(value, list):
        return [comment for child in value for comment in comments(child)]
    return []


async def test_preparation_splice_denied_without_client_or_io(tmp_path: Path) -> None:
    consumer, prepared = composition(tmp_path, httpx2.MockTransport(lambda _: httpx2.Response(500)))
    changed = prepared.model_copy(update={"request_sha256": "f" * 64})
    with pytest.raises(ValueError):
        await consumer.request_once(changed, now=datetime.now(UTC))


async def saved_outcome(
    consumer: RegisteredPlanningConsumer, prepared: PreparedPlanningRequest
) -> GovernedModelResult:
    import json

    call = prepared.request
    emitted = content()
    tasks = emitted["tasks"]
    assert isinstance(tasks, list)
    tasks[0]["evidence_ids"] = [str(prepared.context.manifest.inclusions[0].handle.evidence_id)]
    result = CompanyModelResult(
        request_id=call.request_id,
        status="response",
        billing="known",
        usage=TokenUsage(
            input_tokens=100, output_tokens=20, cached_input_tokens=0, reasoning_tokens=5
        ),
        structured_json=json.dumps(emitted),
    )
    envelope = ModelEvidence(
        request=call,
        request_hash=request_hash(call),
        action_hash="a" * 64,
        model=planning_registry("openai").models[0],
        registry_revision=call.registry_revision,
        price_version=call.price_version,
        recipe=prepared.input_recipe,
        input_estimate=FixtureEstimator().estimate(
            call, planning_registry("openai"), prepared.input_recipe
        ),
        result=result,
        source_event_at=datetime.now(UTC),
        checked_at=datetime.now(UTC),
        owner_id=call.actor_id,
    )
    artifact = await consumer.evidence.save(envelope)
    recorded = RecordedModelOutcome(
        artifact=artifact,
        billing="known",
        actual_usd=Decimal("0.000360"),
        stop_required=False,
        receipt_id=uuid5(call.action_id, "model-receipt-v1"),
    )
    return GovernedModelClient._outcome(result, recorded, state="verifying")


@pytest.mark.parametrize("failure", ["failed", "unknown", "recording", "release", "cancelled"])
async def test_unsuccessful_native_outcome_never_adopts_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    consumer, prepared = composition(tmp_path, httpx2.MockTransport(lambda _: httpx2.Response(500)))
    known = await saved_outcome(consumer, prepared)
    assert known.recorded is not None
    recorded = known.recorded.model_copy(update={"stop_required": True})
    if failure == "unknown":
        provider = CompanyModelResult(
            request_id=prepared.request.request_id, status="failed", billing="unknown"
        )
        unknown = recorded.model_copy(
            update={"billing": "unknown", "actual_usd": None, "receipt_id": None}
        )
        result = GovernedModelClient._outcome(provider, unknown, state="outcome_unknown")
    elif failure == "recording":
        result = GovernedModelClient._outcome(
            known.provider_result, recording_error="recording_denied", state="blocked"
        )
    elif failure == "release":
        result = GovernedModelClient._outcome(
            known.provider_result, known.recorded, release_error="release_denied"
        )
    else:
        result = GovernedModelClient._outcome(
            known.provider_result.model_copy(update={"status": "failed"}), recorded, state="blocked"
        )
    client_call = AsyncMock(return_value=result)
    cancelled = GovernedModelCancelledError(result)
    if failure == "cancelled":
        client_call.side_effect = cancelled
    monkeypatch.setattr(GovernedModelClient, "request_once", client_call)
    if failure == "cancelled":
        with pytest.raises(GovernedModelCancelledError) as caught:
            await consumer.request_once(prepared, now=datetime.now(UTC))
        assert caught.value is cancelled
    else:
        attempt = await consumer.request_once(prepared, now=datetime.now(UTC))
        assert attempt.candidate is None and attempt.denial == "model_outcome"
        assert attempt.governed is result
    assert consumer.evidence_reads == ()


@pytest.mark.parametrize("failure", ["missing", "tamper", "foreign_artifact", "cost", "receipt"])
async def test_adoption_requires_exact_protected_native_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from uuid import UUID

    consumer, prepared = composition(tmp_path, httpx2.MockTransport(lambda _: httpx2.Response(500)))
    known = await saved_outcome(consumer, prepared)
    assert known.recorded is not None
    recorded = known.recorded
    path = Path(recorded.artifact.reference)
    if failure == "missing":
        path.unlink()
    elif failure == "tamper":
        path.chmod(0o600)
        path.write_text("{}")
    elif failure == "foreign_artifact":
        recorded = recorded.model_copy(
            update={"artifact": recorded.artifact.model_copy(update={"artifact_id": UUID(int=999)})}
        )
    elif failure == "cost":
        recorded = recorded.model_copy(update={"actual_usd": Decimal("0.000001")})
    else:
        recorded = recorded.model_copy(update={"receipt_id": UUID(int=999)})
    known = known.model_copy(update={"recorded": recorded})
    monkeypatch.setattr(GovernedModelClient, "request_once", AsyncMock(return_value=known))
    attempt = await consumer.request_once(prepared, now=datetime.now(UTC))
    assert attempt.candidate is None
    assert attempt.denial in {"evidence_unavailable", "evidence_mismatch"}
    assert attempt.governed is known


async def test_cancel_during_actual_read_retains_owner_and_known_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from nexus.company.management.planning_consumer import PlanningReadCancelledError

    consumer, prepared = composition(tmp_path, httpx2.MockTransport(lambda _: httpx2.Response(500)))
    known = await saved_outcome(consumer, prepared)
    assert known.recorded is not None
    original = consumer.evidence.load
    entered, finish = asyncio.Event(), asyncio.Event()

    async def delayed(reference: ArtifactRef) -> ModelEvidence:
        entered.set()
        await finish.wait()
        return await original(reference)

    monkeypatch.setattr(consumer.evidence, "load", delayed)
    monkeypatch.setattr(GovernedModelClient, "request_once", AsyncMock(return_value=known))
    task = asyncio.create_task(consumer.request_once(prepared, now=datetime.now(UTC)))
    await entered.wait()
    task.cancel()
    with pytest.raises(PlanningReadCancelledError) as caught:
        await task
    owner = caught.value.evidence_read
    assert caught.value.governed.recorded == known.recorded
    assert consumer.evidence_reads == (owner,) and not owner.done()
    finish.set()
    await owner
