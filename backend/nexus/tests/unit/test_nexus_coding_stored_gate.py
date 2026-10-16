"""Actual EffectStore composition fence; supplied SQL/allowance is not C admission proof.

H's real TinyGit/protected files and genuine signed actor produce the original
worker seal. The synthetic fixture's USD allocation is not live affordability;
SQL/native allowance delivery is explicitly supplied as in the existing D tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from time import monotonic_ns
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.company.brain.model_context_check import BrainModelContextCheck
from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
from nexus.company.management.coding_intent import CodingIntentCheck
from nexus.company.management.coding_prepared_contracts import StoredCodingRequest
from nexus.company.management.coding_stored_intent import StoredCodingIntent
from nexus.company.management.nexus_coding_model_intent import NexusCodingModelIntentCheck
from nexus.core.llm.company_pricing import quote_cost
from nexus.execution.effect_store import EffectStore
from nexus.execution.intent_checks import BeforeIntentCheck, CompositeBeforeIntentCheck
from nexus.execution.nexus_intent_gate import bind_nexus_intent_check
from nexus.execution.runtime_contracts import AttemptKind
from nexus.harness.canonical import action_hash
from nexus.harness.model_input_estimator import FullContextInputEstimator
from nexus.harness.model_intent import ModelIntentCheck
from nexus.tests.unit.nexus_intent_fixture import Boundary
from nexus.tests.unit.test_coding_prepared_store import saved_case
from nexus.tests.unit.test_nexus_coding_gate import coding_boundary


@dataclass
class Case:
    native: Boundary
    effects: EffectStore
    checks: CompositeBeforeIntentCheck
    stored: StoredCodingIntent
    model: ModelIntentCheck
    caps: AsyncMock


async def installed(root: Path, monkeypatch: pytest.MonkeyPatch) -> Case:
    store, prepared, lease, credential, delivery = await saved_case(root, monkeypatch)
    loaded = await store.load_worker(
        lease,
        credential,
        prepared.request.action_id,
        end_us=monotonic_ns() // 1000 + 10_000_000,
    )
    brain = BrainModelContextCheck(
        store.contexts,
        prepared.context,
        prepared.scope,
        credential.identity,
        prepared.request,
        prepared.input_recipe,
        lease,
        allowed_classification=prepared.request.data_classification,
    )
    genuine = NexusCodingModelIntentCheck(
        CodingIntentCheck(brain, prepared, registry=store.management.catalog.models), credential
    )
    stored = StoredCodingIntent(genuine, store, loaded)
    value = coding_boundary(monkeypatch, 1)
    value.catalog = store.management.catalog
    value.lease = lease
    value.identity = credential.identity
    value.now = datetime.now(UTC)
    value.work.worker_id, value.work.segment_id, value.work.fence = (
        lease.worker_id,
        lease.segment_id,
        lease.fence,
    )
    value.work.lease_until = lease.expires_at
    assert delivery.action is not None
    proposal = delivery.action
    modelrow = next(
        row
        for row in value.catalog.models.models
        if row.registry_id == prepared.request.registry_id
    )
    quote = quote_cost(modelrow.price, prepared.request.bounds, now=value.now)
    proposal = proposal.model_copy(update={"estimated_cost_usd": quote.amount_usd})
    value.action.id = proposal.action_id
    value.action.proposal_json = proposal.model_dump_json()
    value.action.proposal_hash = action_hash(proposal)
    value.action.approval_json = ApprovalDecision(
        company_id=proposal.company_id,
        decision_id=UUID(int=2001),
        action_id=proposal.action_id,
        action_revision=proposal.revision,
        action_hash=value.action.proposal_hash,
        approver_id=value.control.owner_id,
        decision="approved",
        issued_at=value.now,
        expires_at=lease.expires_at,
    ).model_dump_json()
    value.hold.action_id, value.hold.amount_usd = proposal.action_id, quote.amount_usd
    value.install(monkeypatch)
    effects = store.management.effect_store(store.factory)
    monkeypatch.setattr(effects, "revalidate_execution_locked", AsyncMock())
    monkeypatch.setattr(CodingIntentCheck, "validate", AsyncMock())
    # Current native action is supplied to H unchanged; its real store header
    # joins and source checks still run before/after the real model hook.
    delivery.action = proposal
    model = ModelIntentCheck(
        prepared.request,
        quote,
        lease,
        value.catalog.models,
        FullContextInputEstimator(value.catalog.models, prepared.input_recipe),
        prepared.input_recipe,
        prepared.request.data_classification,
        model_observations=value.catalog.model_observations,
    )
    from nexus.company.directory_models import RegisteredWork
    from nexus.harness.journal_models import DailyBudget, WorkBudget

    admission = store.management.catalog.nexus_coding_admission
    assert admission is not None
    previous_get = value.session.get.side_effect

    async def get(model_type: type[object], selector: object) -> object | None:
        if model_type is DailyBudget:
            return None
        if model_type is RegisteredWork:
            return RegisteredWork(
                company_id=lease.company_id,
                task_id=lease.task_id,
                parent_task_id=admission.procedure.binding.task_id,
                allocation_usd=Decimal("0.1"),
                delegated_usd=Decimal(0),
            )
        if model_type is WorkBudget:
            return WorkBudget(
                company_id=lease.company_id,
                task_id=lease.task_id,
                held_usd=quote.amount_usd,
                spent_usd=Decimal(0),
            )
        delivered: object | None = await previous_get(model_type, selector)
        return delivered

    value.session.get = AsyncMock(side_effect=get)
    caps = AsyncMock(wraps=model._require_caps)
    monkeypatch.setattr(model, "_require_caps", caps)
    return Case(
        value, effects, CompositeBeforeIntentCheck((stored, model, stored)), stored, model, caps
    )


async def test_exact_real_store_issued_c_composite_has_native_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = await installed(tmp_path, monkeypatch)
    gate = bind_nexus_intent_check(
        case.stored.factory,
        case.effects,
        case.native.work,
        case.native.lease,
        case.native.identity,
        case.native.action,
        "model_requests",
        case.checks,
        now=case.native.now,
    )
    gate.require_current(case.native.work, case.native.action, case.checks)
    gate.validate_time(case.native.now)
    assert gate.children and not case.native.added
    case.caps.assert_not_awaited()


async def test_real_native_model_affordability_denies_the_unchanged_synthetic_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = await installed(tmp_path, monkeypatch)
    assert case.model.quote.amount_usd == Decimal("1.049088")
    admission = case.native.catalog.nexus_coding_admission
    assert admission is not None
    assert admission.slots[1].child.allocation_usd == Decimal("0.1")
    with pytest.raises(ValueError, match="allowance"):
        await case.effects.begin(
            case.native.lease,
            case.native.identity,
            case.native.action.id,
            kind="model_requests",
            before_intent=case.checks,
        )
    case.caps.assert_awaited_once()
    assert not case.native.added and case.native.work.model_requests_used == 0
    assert case.native.hold.state == "held"
    case.native.move.assert_not_awaited()


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "noop",
        "bare",
        "actor",
        "copy",
        "foreign-factory",
        "foreign-identity",
        "wrong-kind",
        "parameters",
        "admission",
        "source",
        "check",
    ],
)
async def test_missing_foreign_or_changed_proofs_never_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    case = await installed(tmp_path, monkeypatch)
    check = case.checks
    kind: AttemptKind = "tool_attempts" if fault == "wrong-kind" else "model_requests"
    if fault == "foreign-identity":
        case.native.identity = case.native.identity.model_copy(
            update={"principal_id": UUID(int=9999)}
        )
    supplied: BeforeIntentCheck | None
    if fault == "missing":
        supplied = None
    elif fault == "noop":
        supplied = AsyncMock()
    elif fault == "bare":
        supplied = CompositeBeforeIntentCheck(
            (case.stored.original, case.model, case.stored.original)
        )
    else:
        supplied = check
        if fault == "actor":
            loaded = await case.stored.store.load_actor(
                case.stored.stored.prepared.scope,
                case.stored.credential,
                case.native.action.id,
                end_us=case.stored.stored.read_end_us,
            )
            case.stored.stored = loaded
        elif fault == "copy":
            old = case.stored.stored
            case.stored.stored = StoredCodingRequest(
                old.prepared, old.reference, old.header, old.read_end_us
            )
        elif fault == "foreign-factory":
            from sqlalchemy.ext.asyncio import async_sessionmaker

            case.effects._factory = async_sessionmaker()
        elif fault == "parameters":
            proposal = ActionProposal.model_validate_json(case.native.action.proposal_json)
            proposal = proposal.model_copy(
                update={"parameters": {**proposal.parameters, "request_hash": "f" * 64}}
            )
            case.native.action.proposal_json = proposal.model_dump_json()
            case.native.action.proposal_hash = action_hash(proposal)
        elif fault == "admission":
            case.effects._management_catalog = case.native.catalog.model_copy(
                update={"nexus_coding_admission": None}
            )
        elif fault == "source":
            case.stored.store.sources.artifacts.blobs = case.stored.store.blobs
        else:
            supplied = CompositeBeforeIntentCheck((case.stored, case.model, case.stored.original))
    with pytest.raises(ValueError):
        await case.effects.begin(
            case.native.lease,
            case.native.identity,
            case.native.action.id,
            kind=kind,
            before_intent=supplied,
        )
    assert not case.native.added and case.native.work.model_requests_used == 0
    case.native.move.assert_not_awaited()
    case.caps.assert_not_awaited()


@pytest.mark.parametrize(
    "fault",
    [
        "call",
        "quote",
        "recipe",
        "classification",
        "observations",
        "estimator",
        "registry",
        "lease",
        "source",
        "check",
    ],
)
async def test_original_shape_cannot_swap_during_awaits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    case = await installed(tmp_path, monkeypatch)
    gate = bind_nexus_intent_check(
        case.stored.factory,
        case.effects,
        case.native.work,
        case.native.lease,
        case.native.identity,
        case.native.action,
        "model_requests",
        case.checks,
        now=case.native.now,
    )
    if fault == "call":
        case.model.call = case.model.call.model_copy()
    elif fault == "quote":
        case.model.quote = case.model.quote.model_copy()
    elif fault == "recipe":
        case.model.recipe = case.model.recipe.model_copy()
    elif fault == "classification":
        case.model.classification = "public"
    elif fault == "observations":
        from nexus.tests.unit.test_company_model_observations import observed

        case.model.observations = (observed(),)
    elif fault == "estimator":
        case.model.estimator = FullContextInputEstimator(case.model.registry, case.model.recipe)
    elif fault == "registry":
        case.model.registry = case.model.registry.model_copy()
    elif fault == "lease":
        case.model.lease = case.model.lease.model_copy(update={"fence": case.model.lease.fence + 1})
    elif fault == "source":
        case.stored.store.sources.artifacts.blobs = case.stored.store.blobs
    else:
        case.checks._checks = (case.stored, case.model, case.stored.original)
    with pytest.raises(ValueError):
        gate.require_current(case.native.work, case.native.action, case.checks)


async def test_same_original_source_cutoff_after_actual_estimator_cpu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The actual estimator returns the same proof at a supplied expired original clock."""
    from nexus.company.management import planning_native_facts

    case = await installed(tmp_path, monkeypatch)
    gate = bind_nexus_intent_check(
        case.stored.factory,
        case.effects,
        case.native.work,
        case.native.lease,
        case.native.identity,
        case.native.action,
        "model_requests",
        case.checks,
        now=case.native.now,
    )
    actual = FullContextInputEstimator.estimate
    end = case.stored.stored.read_end_us

    from nexus.core.llm.company_adapter_contracts import CompanyModelRequest
    from nexus.core.llm.company_registry import ModelRegistry
    from nexus.harness.model_authorizer_contracts import InputEstimate, ModelInputRecipe

    def delayed(
        self: FullContextInputEstimator,
        call: CompanyModelRequest,
        registry: ModelRegistry,
        recipe: ModelInputRecipe,
    ) -> InputEstimate:
        value = actual(self, call, registry, recipe)
        monkeypatch.setattr(planning_native_facts, "clock_us", lambda: end)
        return value

    monkeypatch.setattr(FullContextInputEstimator, "estimate", delayed)
    with pytest.raises(TimeoutError):
        gate.require_current(case.native.work, case.native.action, case.checks)
