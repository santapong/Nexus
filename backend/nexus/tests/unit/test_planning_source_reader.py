"""Real protected files and exact native DTO joins; SQL delivery is explicitly supplied.

These are not PostgreSQL/current-owner integration or provider qualification tests.
The cohesive >400-line fixture keeps exact native-envelope inputs, actual protected
file revalidation and cancellation-owner assertions together without another fixture layer.
"""

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import PlanSourceFreshness
from nexus.company.management.planning_content import PlanningBinding, planning_schema
from nexus.company.management.planning_native_facts import NativePlanning, read_end
from nexus.company.management.planning_proposal_bridge import map_content
from nexus.company.management.planning_source_reader import PlanningSource, PlanningSourceReader
from nexus.core.llm.company_adapter_contracts import CompanyModelResult, request_hash
from nexus.core.llm.company_pricing import TokenBounds, TokenUsage, reconcile_cost
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl
from nexus.harness.model_authorizer_contracts import model_action_parameters
from nexus.harness.model_evidence import FileModelEvidenceStore, ModelEvidence
from nexus.tests.integration.test_company_model_authorizer import FixtureEstimator
from nexus.tests.unit.test_company_planning_consumer import planning_registry
from nexus.tests.unit.test_company_planning_intent import prepared_inputs
from nexus.tests.unit.test_planning_proposal_bridge import content, template


async def recorded(tmp_path: Path) -> tuple[PlanningSourceReader, NativePlanning, ModelEvidence]:
    policy = template()
    call, context, _, _, recipe, _ = prepared_inputs()
    base = policy.base_plan
    original = base.payload.children[0]
    bootstrap_child = original.model_copy(
        update={
            "binding": original.binding.model_copy(
                update={
                    "model_profile": recipe.profile,
                    "model_registry_version": call.registry_revision,
                }
            )
        }
    )
    payload = base.payload.model_copy(update={"children": (bootstrap_child,)})
    policy = policy.model_copy(
        update={
            "base_plan": base.model_copy(
                update={"payload": payload, "sha256": canonical_sha256(payload)}
            )
        }
    )
    factory = async_sessionmaker[AsyncSession]()
    blobs = ProtectedBlobStore(tmp_path / "blobs", storage_symbol="fixture")
    retriever = PersistentBrainRetriever(factory, blobs, limits=RetrievalLimits())
    sources = OwnerViewSources(
        BoundedArtifactReader(factory, blobs), cast(PlanSourceFreshness, AsyncMock())
    )
    reader = PlanningSourceReader(
        factory, FileModelEvidenceStore(tmp_path / "models"), retriever, sources, policy
    )
    child = policy.base_plan.payload.children[0].binding
    manifest = context.manifest.model_copy(
        update={
            "task_id": child.task_id,
            "task_trace_id": child.trace_id,
            "actor_id": child.actor_id,
            "principal_id": child.actor_id,
        }
    )
    binding = PlanningBinding(
        goal=policy.base_plan.payload.goal,
        plan_id=policy.base_plan.plan_id,
        expected_plan_revision_id=policy.base_plan.plan_revision_id,
        context_manifest_sha256=canonical_sha256(manifest),
    )
    call = call.model_copy(
        update={
            "task_id": child.task_id,
            "trace_id": child.trace_id,
            "actor_id": child.actor_id,
            "bounds": TokenBounds(input_tokens=28000, max_output_tokens=256),
            "output_schema": planning_schema(binding, manifest=manifest),
        }
    )
    proposal = ActionProposal(
        company_id=call.company_id,
        task_id=call.task_id,
        trace_id=call.trace_id,
        actor_id=call.actor_id,
        action_id=call.action_id,
        revision=1,
        tool="model.request.v1",
        tool_version="v1",
        resource=f"model:{call.registry_id}",
        parameters=model_action_parameters(call, recipe),
        policy_version="v1",
        price_version=call.price_version,
        estimated_cost_usd="0.01",
    )
    now = datetime.now(UTC)
    registry = planning_registry("openai")
    usage = TokenUsage(
        input_tokens=100, output_tokens=20, cached_input_tokens=0, reasoning_tokens=5
    )
    saved = ModelEvidence(
        request=call,
        request_hash=request_hash(call),
        action_hash=action_hash(proposal),
        model=registry.models[0],
        registry_revision=registry.revision,
        price_version=registry.pricebook_version,
        recipe=recipe,
        input_estimate=FixtureEstimator().estimate(call, registry, recipe),
        result=CompanyModelResult(
            request_id=call.request_id,
            status="response",
            billing="known",
            usage=usage,
            structured_json=content().model_dump_json(),
        ),
        source_event_at=now,
        checked_at=now,
        owner_id=child.actor_id,
    )
    ref = await reader.models.save(saved)
    receipt = ActionReceipt(
        company_id=call.company_id,
        receipt_id=uuid5(call.action_id, "model-receipt-v1"),
        action_id=call.action_id,
        task_id=call.task_id,
        trace_id=call.trace_id,
        proposal_hash=saved.action_hash,
        outcome="succeeded",
        recorded_at=now,
        artifacts=(ref,),
    )
    assert saved.model.price is not None
    return (
        reader,
        NativePlanning(
            proposal, receipt, now, reconcile_cost(saved.model.price, usage, now=now).amount_usd
        ),
        saved,
    )


async def test_real_protected_envelope_retains_complete_content_and_maps_exact_slots(
    tmp_path: Path,
) -> None:
    reader, native, saved = await recorded(tmp_path)
    loaded = await reader.models.load(native.receipt.artifacts[0])
    source = reader._interpret(loaded, native)
    assert loaded == saved and source.content == content()
    assert source.content.tasks[0].description and source.content.questions
    assert source.origin.artifact_sha256 == native.receipt.artifacts[0].sha256
    assert (
        map_content(source.content, source.origin, reader.template).procedure
        == reader.template.base_plan.payload.procedure
    )


@pytest.mark.parametrize(
    "change",
    ["v1", "goal", "cas", "artifact", "receipt", "billing", "failed", "content", "cost", "action"],
)
async def test_spliced_or_unusable_recorded_result_cannot_assert_origin(
    tmp_path: Path, change: str
) -> None:
    reader, native, saved = await recorded(tmp_path)
    if change in {"v1", "goal", "cas"}:
        assert saved.request.output_schema is not None
        document = json.loads(saved.request.output_schema.document)
        annotation = json.loads(document["$comment"])
        if change == "v1":
            annotation["version"] = "nexus.company.planning-binding.v1"
        else:
            key = "expected_plan_revision_id" if change == "cas" else "goal"
            annotation["binding"][key] = (
                str(UUID(int=999))
                if change == "cas"
                else (annotation["binding"][key] | {"revision_id": str(UUID(int=999))})
            )
        document["$comment"] = json.dumps(annotation)
        from nexus.core.llm.company_adapter_contracts import JsonSchemaDocument

        saved = saved.model_copy(
            update={
                "request": saved.request.model_copy(
                    update={"output_schema": JsonSchemaDocument(schema_json=json.dumps(document))}
                )
            }
        )
    elif change == "artifact":
        native = NativePlanning(
            native.proposal,
            native.receipt.model_copy(
                update={
                    "artifacts": (
                        native.receipt.artifacts[0].model_copy(
                            update={"artifact_id": UUID(int=999)}
                        ),
                    )
                }
            ),
            native.intent_created_at,
            native.actual_usd,
        )
    elif change == "receipt":
        native = NativePlanning(
            native.proposal,
            native.receipt.model_copy(
                update={"recorded_at": native.receipt.recorded_at.replace(year=2020)}
            ),
            native.intent_created_at,
            native.actual_usd,
        )
    elif change == "cost":
        native = NativePlanning(
            native.proposal, native.receipt, native.intent_created_at, Decimal(0)
        )
    elif change == "action":
        native = NativePlanning(
            native.proposal.model_copy(update={"actor_id": UUID(int=999)}),
            native.receipt,
            native.intent_created_at,
            native.actual_usd,
        )
    else:
        update = (
            {"billing": "unknown"}
            if change == "billing"
            else {"status": "failed"}
            if change == "failed"
            else {
                "structured_json": content()
                .model_copy(
                    update={
                        "tasks": (
                            content()
                            .tasks[0]
                            .model_copy(update={"evidence_ids": (UUID(int=999),)}),
                        )
                    }
                )
                .model_dump_json()
            }
        )
        saved = saved.model_copy(update={"result": saved.result.model_copy(update=update)})
    with pytest.raises(ValueError):
        reader._interpret(saved, native)


async def test_current_read_denial_precedes_model_file_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import nexus.company.management.planning_source_reader as module

    reader, native, _ = await recorded(tmp_path)
    read = AsyncMock(wraps=reader.models.load)
    monkeypatch.setattr(reader.models, "load", read)
    monkeypatch.setattr(
        module, "native_planning", AsyncMock(side_effect=ValueError("current READ denied"))
    )
    scope = CompanyControlScope(
        company_id=native.proposal.company_id,
        principal_id=UUID(int=103),
        operation_id=UUID(int=400),
        trace_id=UUID(int=401),
    )
    with pytest.raises(ValueError):
        await reader._load_locked(
            cast(AsyncSession, object()),
            cast(CompanyControl, object()),
            scope,
            VerifiedIdentity(principal_id=scope.principal_id, workspace_id=UUID(int=2)),
            native.proposal.action_id,
            None,
            read_end(),
        )
    read.assert_not_awaited()


async def test_cancelled_protected_read_retains_actual_owner_and_never_adopts_late_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import nexus.company.management.planning_source_reader as module

    reader, native, _ = await recorded(tmp_path)
    entered, finish = asyncio.Event(), asyncio.Event()
    original = reader.models.load

    async def delayed(ref: object) -> ModelEvidence:
        entered.set()
        await finish.wait()
        return await original(native.receipt.artifacts[0])

    monkeypatch.setattr(reader.models, "load", delayed)
    monkeypatch.setattr(module, "native_planning", AsyncMock(return_value=native))
    scope = CompanyControlScope(
        company_id=native.proposal.company_id,
        principal_id=UUID(int=103),
        operation_id=UUID(int=400),
        trace_id=UUID(int=401),
    )
    task = asyncio.create_task(
        reader._load_locked(
            cast(AsyncSession, object()),
            cast(CompanyControl, object()),
            scope,
            VerifiedIdentity(principal_id=scope.principal_id, workspace_id=UUID(int=2)),
            native.proposal.action_id,
            None,
            read_end(),
        )
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError) as caught:
        await task
    owners = reader.pending_owners()
    assert len(owners) == 1 and not owners[0].cancelled()
    assert vars(caught.value)["_nexus_planning_pending"] == owners
    finish.set()
    await owners[0]
    assert reader.pending_owners() == ()


async def test_posted_origin_without_concrete_store_reader_denied_before_transaction() -> None:
    from nexus.company.management.plan_catalog import PlanAdmissionCatalog
    from nexus.tests.unit.test_planning_proposal_bridge import origin

    policy = template()
    data = map_content(content(), origin(policy), policy)
    store = ManagementPlanStore(
        async_sessionmaker[AsyncSession](),
        PlanAdmissionCatalog(
            company_id=data.company_id,
            models=planning_registry("openai"),
            admitted_profiles=frozenset({"routine"}),
            check_recipes=frozenset(),
        ),
    )
    scope = CompanyControlScope(
        company_id=data.company_id,
        principal_id=UUID(int=103),
        operation_id=UUID(int=400),
        trace_id=UUID(int=401),
    )
    with pytest.raises(ValueError, match="concrete reader"):
        await store.propose(
            scope,
            VerifiedIdentity(principal_id=scope.principal_id, workspace_id=UUID(int=2)),
            data,
            expected_current_revision_id=policy.base_plan.plan_revision_id,
        )


@pytest.mark.parametrize("corrupt", [False, True])
async def test_each_final_interpretation_rereads_actual_private_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corrupt: bool,
) -> None:
    import nexus.company.management.planning_source_reader as module

    reader, native, saved = await recorded(tmp_path)
    source = reader._interpret(saved, native)
    monkeypatch.setattr(module, "native_planning", AsyncMock(return_value=native))
    monkeypatch.setattr(
        module, "require_resources", AsyncMock(return_value=source.manifest.contributors)
    )
    monkeypatch.setattr(module, "heads", AsyncMock(return_value=source.manifest.source_heads))
    monkeypatch.setattr(module, "db_clock", AsyncMock(return_value=saved.checked_at))
    monkeypatch.setattr(reader.retriever, "revalidate_handles", AsyncMock())
    scope = CompanyControlScope(
        company_id=native.proposal.company_id,
        principal_id=UUID(int=103),
        operation_id=UUID(int=400),
        trace_id=UUID(int=401),
    )

    async def load() -> PlanningSource:
        return await reader._load_locked(
            cast(AsyncSession, object()),
            cast(CompanyControl, object()),
            scope,
            VerifiedIdentity(principal_id=scope.principal_id, workspace_id=UUID(int=2)),
            native.proposal.action_id,
            None,
            read_end(),
        )

    assert await load() == source
    path = Path(native.receipt.artifacts[0].reference)
    if corrupt:
        path.chmod(0o600)
        path.write_bytes(b"{}")
    else:
        path.unlink()
    with pytest.raises((ValueError, OSError)):
        await load()
