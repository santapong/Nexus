"""Real context/whole-input classes; supplied native delivery is not SQL admission proof.

The cohesive test-size exception keeps the one full C catalog/context composition
next to its native predicate and genuine-witness matrix; consumer tests reuse it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import jwt
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.context import ContextAuthorityState, ContextLimits
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.model_context_check import BrainModelContextCheck
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_content import coding_schema
from nexus.company.management.coding_intent import (
    CodingIntentCheck,
    PreparedCodingRequest,
    prepare_coding_request,
    require_coding_registry,
)
from nexus.company.management.governance_models import ManagementGoalHead, ManagementGoalRevision
from nexus.company.management.lifecycle import PlanRevision, PlanRevisionRef
from nexus.company.management.nexus_coding_model_intent import NexusCodingModelIntentCheck
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.management.planning_authority import (
    ManagementPlanningAuthority,
    PlanningRolePolicy,
)
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    NotificationWorkerIdentities,
)
from nexus.core.llm.company_pricing import TokenBounds
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.planning_application_config import PlanningSourcePolicies
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.model_input_estimator import FullContextInputEstimator
from nexus.tests.unit.test_coding_sources import source_case
from nexus.tests.unit.test_company_input_bounds import supported
from nexus.tests.unit.test_company_input_estimator import recipe
from nexus.tests.unit.test_company_provider_conformance import request
from nexus.tests.unit.test_nexus_coding_admission import planning_origin
from nexus.tests.unit.test_nexus_coding_catalog import coding_case


def prepared_case() -> tuple[
    PreparedCodingRequest, PlanAdmissionCatalog, FullContextInputEstimator, ExecutionLease
]:
    """Keep the complete synthetic family/context/proof fixture together (>50 lines).

    No declaration or supplied eligibility is a real native registration/quality fact.
    """
    value, catalog = coding_case()
    coder = value.slots[1]
    selected = supported("google").models[0]
    original = catalog.models.models[1]
    selected = selected.model_copy(
        update={
            "registry_id": original.registry_id,
            "endpoint_id": original.endpoint_id,
            "price": original.price,
            "allowed_data": frozenset({"internal", "confidential"}),
        }
    )
    registry = catalog.models.model_copy(
        update={"models": (catalog.models.models[0], selected, *catalog.models.models[2:])}
    )
    digest = canonical_sha256(registry)
    value = value.model_copy(update={"registry_sha256": digest})
    catalog = PlanAdmissionCatalog.model_validate_json(
        catalog.model_copy(
            update={
                "models": registry,
                "nexus_coding_admission": value,
                "native_profiles": tuple(
                    row.model_copy(update={"registry_sha256": digest})
                    for row in catalog.native_profiles
                ),
                "notification_profiles": tuple(
                    row.model_copy(update={"registry_sha256": digest})
                    for row in catalog.notification_profiles
                ),
            }
        ).model_dump_json()
    )
    policy = recipe(evaluation_suite_version="frozen-1")
    bound = coder.child.binding
    scope = BrainReadScope(
        company_id=value.company_id,
        workspace_id=bound.workspace_id,
        principal_id=bound.actor_id,
        operation_id=UUID(int=501),
        trace_id=UUID(int=502),
        task_id=bound.task_id,
        task_trace_id=bound.trace_id,
        actor_id=bound.actor_id,
    )
    authority = ContextAuthorityState(
        company_id=value.company_id,
        mandate_version="m1",
        policy_version="p1",
        budget_version=registry.pricebook_version,
        role_system_text="Code from complete pinned Nexus source DATA.",
        data_classification="internal",
        model_profile="engineering",
        model_recipe=policy.recipe_id,
        model_recipe_revision=policy.revision,
    )
    binding, context, sources, _ = source_case(scope, authority)
    payload = value.payload("execution", origin=planning_origin(value))
    plan = PlanRevision(
        company_id=value.company_id,
        plan_id=value.plan_id,
        plan_revision_id=UUID(int=503),
        revision=payload.plan.revision,
        sha256=canonical_sha256(payload),
        payload=payload,
        proposed_by=value.procedure.binding.actor_id,
        recorded_at=datetime.now(UTC),
    )
    ref = PlanRevisionRef.model_validate(
        {name: getattr(plan, name) for name in PlanRevisionRef.model_fields}
    )
    binding = binding.model_copy(update={"goal": value.goal, "plan": ref, "run_id": bound.run_id})
    call = request(
        company_id=value.company_id,
        registry_id=selected.registry_id,
        registry_revision=registry.revision,
        price_version=registry.pricebook_version,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        action_id=UUID(int=504),
        attempt_id=UUID(int=504),
        request_id=UUID(int=505),
        input_text=context.input_text,
        system_text=context.system_text,
        data_classification=context.manifest.data_classification,
        bounds=TokenBounds(
            input_tokens=1_048_576, max_output_tokens=512, input_bound_kind="model_input_ceiling_v1"
        ),
        output_schema=coding_schema(binding, manifest=context.manifest),
    )
    estimator = FullContextInputEstimator(registry, policy)
    prepared = prepare_coding_request(
        call,
        context,
        binding,
        scope=scope,
        sources=sources,
        input_recipe=policy,
        catalog=catalog,
        input_estimator=estimator,
    )
    lease = ExecutionLease(
        company_id=value.company_id,
        workspace_id=bound.workspace_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        run_id=bound.run_id,
        workflow_version="v1",
        segment_id=UUID(int=506),
        worker_id=UUID(int=507),
        fence=1,
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
        mode="execute",
    )
    return prepared, catalog, estimator, lease


class Credential:
    def __init__(self, prepared: PreparedCodingRequest, seconds: int = 60) -> None:
        self.prepared, self.seconds = prepared, seconds

    async def credential(self) -> SecretStr:
        now = datetime.now(UTC)
        return SecretStr(
            jwt.encode(
                {
                    "sub": str(self.prepared.binding.actor_id),
                    "workspace_id": str(self.prepared.binding.workspace_id),
                    "iat": int(now.timestamp()),
                    "exp": int((now + timedelta(seconds=self.seconds)).timestamp()),
                },
                "synthetic-coding-key-which-is-long-enough",
                algorithm="HS256",
            )
        )


async def witness(prepared: PreparedCodingRequest) -> AuthenticatedWorkerIdentity:
    return await NotificationWorkerIdentities(
        Credential(prepared), SecretStr("synthetic-coding-key-which-is-long-enough"), enabled=True
    ).current()


def test_preparation_freezes_complete_source_schema_estimate_and_nine_parameter_fingerprint() -> (
    None
):
    prepared, catalog, estimator, _ = prepared_case()
    assert require_coding_registry(prepared, catalog.models) == catalog.models.models[1]
    assert prepared.input_estimate == estimator.estimate(
        prepared.request, catalog.models, prepared.input_recipe
    )
    assert prepared.input_estimate.whole_request is not None
    admission = catalog.nexus_coding_admission
    assert admission is not None
    assert prepared.admission_sha256 == canonical_sha256(admission)
    assert len(prepared.model_parameters_sha256) == 64
    assert "old\\n" in prepared.request.input_text


@pytest.mark.parametrize(
    "fault", ["input", "schema", "parameters", "context", "source", "proof", "profile", "goal"]
)
def test_unchecked_prepared_splices_are_denied(fault: str) -> None:
    prepared, _, _, _ = prepared_case()
    if fault == "input":
        prepared = prepared.model_copy(
            update={
                "request": prepared.request.model_copy(
                    update={"input_text": "code only in annotation"}
                )
            }
        )
    elif fault == "schema":
        prepared = prepared.model_copy(
            update={"request": prepared.request.model_copy(update={"output_schema": None})}
        )
    elif fault == "parameters":
        prepared = prepared.model_copy(update={"model_parameters_sha256": "f" * 64})
    elif fault == "context":
        prepared = prepared.model_copy(
            update={"context": prepared.context.model_copy(update={"system_text": "new authority"})}
        )
    elif fault == "source":
        prepared = prepared.model_copy(update={"sources": prepared.sources[:1]})
    elif fault == "proof":
        prepared = prepared.model_copy(
            update={
                "input_estimate": prepared.input_estimate.model_copy(update={"whole_request": None})
            }
        )
    elif fault == "profile":
        prepared = prepared.model_copy(
            update={"input_recipe": prepared.input_recipe.model_copy(update={"profile": "routine"})}
        )
    else:
        prepared = prepared.model_copy(
            update={
                "binding": prepared.binding.model_copy(
                    update={
                        "goal": prepared.binding.goal.model_copy(
                            update={"company_id": UUID(int=999)}
                        )
                    }
                )
            }
        )
    with pytest.raises(ValueError):
        PreparedCodingRequest.model_validate_json(prepared.model_dump_json(by_alias=True))


def test_crossed_actual_registry_or_model_whole_proof_is_denied() -> None:
    prepared, catalog, _, _ = prepared_case()
    changed = catalog.models.model_copy(update={"revision": "changed"})
    with pytest.raises(ValueError):
        require_coding_registry(prepared, changed)
    proof = prepared.input_estimate.whole_request
    assert proof is not None
    forged = prepared.model_copy(
        update={
            "input_estimate": prepared.input_estimate.model_copy(
                update={"whole_request": proof.model_copy(update={"model_sha256": "f" * 64})}
            )
        }
    )
    with pytest.raises(ValueError):
        require_coding_registry(forged, catalog.models)


def runtime_graph(
    root: Path, prepared: PreparedCodingRequest, catalog: PlanAdmissionCatalog
) -> tuple[
    async_sessionmaker[AsyncSession], ManagementExecutionServices, PersistentContextAssembler
]:
    factory = async_sessionmaker[AsyncSession]()
    blobs = ProtectedBlobStore(root / "brain", storage_symbol="coding-fixture")
    policies = PlanningSourcePolicies(
        policies=(
            SourcePolicy(
                source_symbol=prepared.sources[0].git.source_symbol,
                authority_profile="owner.primary.v1",
                data_classification="confidential",
                media_type="text/plain",
                parser_version="utf8-identity-v1",
                chunker_version="utf8-sections-v1",
                search_config="simple",
                freshness_seconds=None,
                allowed_external_keys=frozenset(row.git.external_key for row in prepared.sources),
            ),
        )
    )
    management = ManagementExecutionServices(
        catalog, BoundedArtifactReader(factory, blobs), RegisteredSourceFreshness(factory, policies)
    )
    authority = ManagementPlanningAuthority(
        management,
        PlanningRolePolicy(
            company_id=catalog.company_id,
            workflow_name="company.coding.v1",
            workflow_version="v1",
            model_profile="engineering",
            data_classification="internal",
            role_system_text="Code from pinned source DATA.",
        ),
        prepared.input_recipe,
    )
    contexts = PersistentContextAssembler(
        factory,
        PersistentBrainRetriever(factory, blobs, limits=RetrievalLimits()),
        authority,
        limits=ContextLimits(policy_version=prepared.context.manifest.policy_version),
    )
    return factory, management, contexts


def original_check(root: Path) -> tuple[CodingIntentCheck, PlanAdmissionCatalog, ExecutionLease]:
    prepared, catalog, _, lease = prepared_case()
    _, _, contexts = runtime_graph(root, prepared, catalog)
    context_check = BrainModelContextCheck(
        contexts,
        prepared.context,
        prepared.scope,
        VerifiedIdentity(principal_id=lease.actor_id, workspace_id=lease.workspace_id),
        prepared.request,
        prepared.input_recipe,
        lease,
        allowed_classification=prepared.request.data_classification,
    )
    return CodingIntentCheck(context_check, prepared, registry=catalog.models), catalog, lease


async def test_wrapper_uses_only_genuine_original_c_actor_and_finite_window(tmp_path: Path) -> None:
    original, _, lease = original_check(tmp_path)
    credential = await witness(original._prepared)
    check = NexusCodingModelIntentCheck(original, credential)
    check.validate_time(datetime.now(UTC))
    with pytest.raises(ValueError):
        check.validate_time(lease.expires_at)
    foreign = original._prepared.model_copy(
        update={
            "binding": original._prepared.binding.model_copy(update={"actor_id": UUID(int=999)})
        }
    )
    with pytest.raises(ValueError):
        NexusCodingModelIntentCheck(original, await witness(foreign))
    check.credential = await witness(original._prepared)
    with pytest.raises(ValueError):
        check.require_composition()


@pytest.mark.parametrize("fault", ["registry", "prepared", "context"])
async def test_original_c_check_rejects_coherent_replacement_before_first_use(
    tmp_path: Path, fault: str
) -> None:
    original, _, _ = original_check(tmp_path)
    check = NexusCodingModelIntentCheck(original, await witness(original._prepared))
    if fault == "registry":
        original._registry = original.registry.model_copy(update={"revision": "changed"})
    elif fault == "prepared":
        original._prepared = original._prepared.model_copy(update={"admission_sha256": "f" * 64})
    else:
        original._context_check._context = original._prepared.context.model_copy(
            update={"input_text": "changed"}
        )
    with pytest.raises(ValueError):
        check.require_composition()


@pytest.mark.parametrize(
    "fault", [None, "goal-head", "goal-sha", "bound-plan", "missing-plan", "full-profile"]
)
async def test_c_native_current_goal_and_approved_durable_full_profile_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    original, catalog, _ = original_check(tmp_path)
    prepared = original._prepared
    admission = catalog.nexus_coding_admission
    assert admission is not None
    payload = admission.payload("execution", origin=planning_origin(admission))
    ref, goal = prepared.binding.plan, prepared.binding.goal
    row = ManagementPlanRevision(
        company_id=ref.company_id,
        plan_id=ref.plan_id,
        plan_revision_id=ref.plan_revision_id,
        revision=ref.revision,
        sha256=ref.sha256,
        snapshot_json=payload.model_dump_json(),
        proposed_by=admission.procedure.binding.actor_id,
        recorded_at=datetime.now(UTC),
    )
    head = ManagementGoalHead(
        company_id=goal.company_id,
        goal_id=goal.goal_id,
        current_revision_id=goal.revision_id,
        active=True,
    )
    revision = ManagementGoalRevision(
        company_id=goal.company_id,
        goal_id=goal.goal_id,
        revision_id=goal.revision_id,
        version=goal.version,
        sha256=goal.sha256,
    )
    bound = CurrentPlanBinding(
        company_id=goal.company_id,
        plan=ref,
        child=admission.slots[1].child,
        work=admission.slots[1].work,
        work_sha256="a" * 64,
        procedure_id=admission.procedure.procedure_id,
    )
    if fault == "goal-head":
        head.current_revision_id = UUID(int=999)
    elif fault == "goal-sha":
        revision.sha256 = "f" * 64
    elif fault == "bound-plan":
        bound = bound.model_copy(update={"plan": ref.model_copy(update={"sha256": "f" * 64})})
    elif fault == "full-profile":
        row.snapshot_json = payload.model_copy(
            update={"coding_admission_sha256": "f" * 64}
        ).model_dump_json()
    session = AsyncMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    session.get.side_effect = [head, revision, None if fault == "missing-plan" else row]
    monkeypatch.setattr(ManagementPlanStore, "current_binding", AsyncMock(return_value=bound))
    # Only native/context IO delivery is supplied; the new C joins below run unchanged.
    monkeypatch.setattr(original._context_check, "validate", AsyncMock())
    control = CompanyControl(company_id=goal.company_id)
    work = ExecutionWork(company_id=goal.company_id, task_id=prepared.request.task_id)
    call = original.validate(
        session, control, work, JournalAction(id=prepared.request.action_id), datetime.now(UTC)
    )
    if fault is None:
        await call
    else:
        with pytest.raises(ValueError):
            await call
