"""Real preparation helpers over supplied SQL rows; no PostgreSQL or provider permission."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import TextClause

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.directory_models import (
    DirectoryCompany,
    DirectoryMembership,
    RegisteredWork,
    WorkPrincipal,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.governance_models import (
    ManagementGoalHead,
    ManagementGoalRevision,
    ManagementMandateHead,
    ManagementMandateRevision,
)
from nexus.company.management.plan_models import ManagementProcedure
from nexus.core.llm.company_adapter_contracts import JsonSchemaDocument, request_hash
from nexus.core.llm.company_registry import ModelRegistration
from nexus.core.llm.qualification_contracts import (
    PROFILE,
    TOOL,
    WORKFLOW,
    QualificationRecipe,
    qualification_parameters,
    recipe_hash,
)
from nexus.execution.qualification_service import QualificationPreparationService
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionRegistration
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import registration_digest
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.lifecycle import ActionState
from nexus.tests.unit.test_qualification_contracts import NOW
from nexus.tests.unit.test_qualification_intent import native


class Rows:
    """Only SQL transport/default/transaction delivery is simulated; native helpers run."""

    def __init__(self, rows: dict[type[object], object]) -> None:
        self.rows, self.now = rows, NOW
        self.expire_after_write = False
        self.commits = self.rollbacks = 0
        self.added: list[object] = []
        self.actions: dict[UUID, JournalAction] = {}
        mock = MagicMock(spec=AsyncSession)
        self.session = cast(AsyncSession, mock)
        mock.__aenter__ = AsyncMock(return_value=self.session)
        mock.__aexit__ = AsyncMock(return_value=False)
        mock.begin = MagicMock(side_effect=self.transaction)
        mock.in_transaction = MagicMock(return_value=True)
        mock.get = AsyncMock(side_effect=self.get)
        mock.scalar = AsyncMock(side_effect=self.scalar)
        mock.scalars = AsyncMock(side_effect=self.scalars)
        mock.execute = AsyncMock()
        mock.add = MagicMock(side_effect=self.add)
        mock.add_all = MagicMock(side_effect=self.add_all)
        mock.flush = AsyncMock(side_effect=self.flush)
        self.factory = cast(async_sessionmaker[AsyncSession], MagicMock(return_value=self.session))

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        before, actions = deepcopy((self.rows, self.actions))
        try:
            yield
        except BaseException:
            self.rows.clear()
            self.rows.update(before)
            self.actions = actions
            self.rollbacks += 1
            raise
        else:
            self.commits += 1

    async def get(self, model: type[object], key: object) -> object | None:
        return self.rows.get(model)

    async def scalar(self, statement: Select[tuple[object]] | TextClause) -> object | None:
        if isinstance(statement, TextClause):
            return False  # Explicitly supplied non-bypass SQL-role observation.
        entity = statement.column_descriptions[0].get("entity")
        if entity is JournalAction:
            return self.actions.get(statement.compile().params["id_1"])
        return self.now if entity is None else self.rows.get(entity)

    async def scalars(self, statement: Select[tuple[object]]) -> MagicMock:
        entity = statement.column_descriptions[0].get("entity")
        row = self.rows.get(entity)
        values = [row.principal_id] if isinstance(row, WorkPrincipal) else [row] if row else []
        return MagicMock(all=MagicMock(return_value=values))

    def add(self, row: object) -> None:
        self.rows[type(row)] = row
        if isinstance(row, JournalAction):
            self.actions[row.id] = row
        self.added.append(row)

    def add_all(self, values: list[object]) -> None:
        for row in values:
            self.add(row)

    async def flush(self) -> None:
        for row in self.added:
            if isinstance(row, ExecutionWork):
                for key in ("fence", "segment_number"):
                    if getattr(row, key) is None:
                        setattr(row, key, 0)
                if row.state is None:
                    row.state = "eligible"
                for kind in AttemptQuota.model_fields:
                    for suffix in ("used", "delegated"):
                        if getattr(row, f"{kind}_{suffix}") is None:
                            setattr(row, f"{kind}_{suffix}", 0)
        if self.expire_after_write and self.added:
            self.now = NOW + timedelta(minutes=10)


async def delivery() -> tuple[Rows, QualificationRecipe, CompanyControlScope, VerifiedIdentity]:
    """Reuse the existing explicitly supplied public goal/mandate/SDK description fixture."""
    check, session, control, _, _, head = native()
    identity = check._identity
    scope = CompanyControlScope(
        company_id=control.company_id,
        principal_id=identity.principal_id,
        operation_id=UUID(int=55),
        trace_id=UUID(int=56),
    )
    data: dict[type[object], object] = {
        CompanyControl: control,
        ManagementGoalHead: head,
        DirectoryCompany: DirectoryCompany(
            company_id=control.company_id,
            workspace_id=identity.workspace_id,
            owner_id=identity.principal_id,
            company_active=True,
            workspace_active=True,
        ),
        DirectoryMembership: DirectoryMembership(
            company_id=control.company_id,
            principal_id=identity.principal_id,
            role="owner",
            principal_active=True,
            membership_active=True,
        ),
    }
    for model in (ManagementGoalRevision, ManagementMandateHead, ManagementMandateRevision):
        data[model] = await session.get(model, None)
    return Rows(data), check._recipe, scope, identity


@pytest.mark.parametrize("schema", [False, True])
async def test_preparation_creates_only_actual_registered_work_and_pending_action(
    schema: bool,
) -> None:
    rows, recipe, scope, identity = await delivery()
    if schema:
        recipe = recipe.model_copy(
            update={"output_schema": JsonSchemaDocument(schema_json='{"type":"object"}')}
        )
    prepared = await QualificationPreparationService(rows.factory, (recipe,)).prepare_qualification(
        scope, identity, recipe.recipe_id
    )
    assert rows.commits == 1 and rows.rollbacks == 0
    assert {type(row) for row in rows.added} == {
        RegisteredWork,
        WorkPrincipal,
        ExecutionWork,
        JournalAction,
    }
    assert prepared.work.registration.work.goal_id == recipe.goal.goal_id
    assert prepared.work.actor_id == identity.principal_id
    assert prepared.work.registration.work.budget_usd == Decimal("1.000000")
    assert prepared.work.registration.quota == AttemptQuota(
        model_requests=12, tool_attempts=0, rework_rounds=0, plan_revisions=0
    )
    registration = prepared.work.registration
    assert (
        registration.workflow_name,
        registration.workflow_version,
        registration.model_profile,
    ) == (WORKFLOW, "v1", PROFILE)
    assert prepared.action.state == ActionState.AWAITING_APPROVAL
    assert prepared.action.approval is None and prepared.action.consumed_at is None
    assert prepared.action.proposal.tool == TOOL
    assert prepared.action.proposal.parameters == qualification_parameters(recipe, prepared.request)
    assert prepared.action.proposal.estimated_cost_usd == prepared.quote.amount_usd
    assert prepared.request.bounds.max_output_tokens == recipe.request_output_cap
    assert prepared.quote.amount_usd > Decimal("0.3")
    assert prepared.recipe_sha256 == recipe_hash(recipe)
    assert prepared.company_completed is False
    assert prepared.work.counters.model_requests == prepared.work.fence == 0
    assert prepared.work.worker_id is None and prepared.work.expires_at is None
    assert "api_key" not in prepared.model_dump_json(by_alias=True)


async def test_same_prepare_is_idempotent_and_does_not_reset_used_counters() -> None:
    rows, recipe, scope, identity = await delivery()
    service = QualificationPreparationService(rows.factory, (recipe,))
    first = await service.prepare_qualification(scope, identity, recipe.recipe_id)
    work = cast(ExecutionWork, rows.rows[ExecutionWork])
    work.model_requests_used = 2
    scope = scope.model_copy(update={"operation_id": UUID(int=77), "trace_id": UUID(int=78)})
    second = await service.prepare_qualification(scope, identity, recipe.recipe_id)
    assert len(rows.added) == 4 and rows.commits == 2
    assert first.request == second.request and first.action == second.action
    assert second.work.counters.model_requests == 2


@pytest.mark.parametrize(
    "fault",
    [
        "identity",
        "role",
        "inactive",
        "goal",
        "mandate",
        "price",
        "work-cap",
        "day-cap",
        "delivery-root",
        "expired",
        "unknown",
    ],
)
async def test_current_admission_denials_leave_no_partial_preparation(fault: str) -> None:
    rows, recipe, scope, identity = await delivery()
    member = cast(DirectoryMembership, rows.rows[DirectoryMembership])
    control = cast(CompanyControl, rows.rows[CompanyControl])
    if fault == "identity":
        identity = identity.model_copy(update={"principal_id": UUID(int=99)})
    elif fault == "role":
        member.role = "admin"
    elif fault == "inactive":
        member.membership_active = False
    elif fault == "goal":
        cast(ManagementGoalHead, rows.rows[ManagementGoalHead]).active = False
    elif fault == "mandate":
        cast(ManagementMandateHead, rows.rows[ManagementMandateHead]).active = False
    elif fault == "price":
        control.price_version = "changed-price"
    elif fault == "work-cap":
        control.work_cap_usd = Decimal("0.5")
    elif fault == "day-cap":
        control.daily_cap_usd = Decimal("0.5")
    elif fault == "delivery-root":
        rows.rows[ManagementProcedure] = ManagementProcedure(
            company_id=scope.company_id, goal_id=recipe.goal.goal_id
        )
    elif fault == "expired":
        rows.now = recipe.valid_until
    service = QualificationPreparationService(rows.factory, (recipe,))
    with pytest.raises(ValueError):
        await service.prepare_qualification(
            scope, identity, "absent" if fault == "unknown" else recipe.recipe_id
        )
    assert (
        RegisteredWork not in rows.rows
        and ExecutionWork not in rows.rows
        and JournalAction not in rows.rows
    )


async def test_expiry_after_real_registration_and_append_rolls_back_all_rows() -> None:
    rows, recipe, scope, identity = await delivery()
    rows.expire_after_write = True
    with pytest.raises(ValueError):
        await QualificationPreparationService(rows.factory, (recipe,)).prepare_qualification(
            scope, identity, recipe.recipe_id
        )
    assert rows.added and rows.rollbacks == 1 and rows.commits == 0
    assert RegisteredWork not in rows.rows and JournalAction not in rows.rows


@pytest.mark.parametrize("fault", ["registry", "target", "allocation", "quota"])
async def test_changed_recipe_cannot_mint_a_new_root_or_reset_immutable_registration(
    fault: str,
) -> None:
    rows, recipe, scope, identity = await delivery()
    first = await QualificationPreparationService(rows.factory, (recipe,)).prepare_qualification(
        scope, identity, recipe.recipe_id
    )
    allocation = Decimal("1.00")
    if fault == "registry":
        recipe = recipe.model_copy(update={"registry_revision": "changed"})
    elif fault == "target":
        target = recipe.target.model_copy(update={"endpoint_id": "another-endpoint"})
        recipe = recipe.model_copy(
            update={"target": target, "qualification_target_sha256s": (canonical_sha256(target),)}
        )
    elif fault == "allocation":
        allocation = Decimal("0.9")
    else:
        existing = cast(ExecutionWork, rows.rows[ExecutionWork])
        registered = ExecutionRegistration.model_validate_json(existing.registration_json)
        registered = registered.model_copy(
            update={"quota": registered.quota.model_copy(update={"model_requests": 11})}
        )
        existing.registration_json = registered.model_dump_json()
        existing.registration_hash = registration_digest(registered)
    with pytest.raises(ValueError):
        await QualificationPreparationService(
            rows.factory, (recipe,), allocation_usd=allocation
        ).prepare_qualification(scope, identity, recipe.recipe_id)
    assert len(rows.added) == 4
    actual = cast(ExecutionWork, rows.rows[ExecutionWork])
    assert actual.task_id == first.work.registration.work.task_id
    assert actual.run_id == first.work.registration.run_id


@pytest.mark.parametrize(
    "allocation", [True, 1.0, "1.00", Decimal("0"), Decimal("6"), Decimal("NaN")]
)
async def test_allocation_is_fixed_exact_and_bounded(allocation: object) -> None:
    rows, recipe, _, _ = await delivery()
    with pytest.raises(ValueError):
        QualificationPreparationService(
            rows.factory, (recipe,), allocation_usd=cast(Decimal, allocation)
        )


async def test_action_request_changes_do_not_change_lifetime_root() -> None:
    rows, recipe, scope, identity = await delivery()
    original = await QualificationPreparationService(rows.factory, (recipe,)).prepare_qualification(
        scope, identity, recipe.recipe_id
    )
    recipe = recipe.model_copy(
        update={"input_text": "A second public qualification case", "case_id": "second"}
    )
    updated = await QualificationPreparationService(rows.factory, (recipe,)).prepare_qualification(
        scope, identity, recipe.recipe_id
    )
    assert original.work.registration == updated.work.registration
    assert original.request.action_id != updated.request.action_id
    assert original.request.request_id != updated.request.request_id
    assert request_hash(original.request) != request_hash(updated.request)


async def test_two_catalogued_providers_share_one_lifetime_work_allowance() -> None:
    rows, first, scope, identity = await delivery()
    target = ModelRegistration.model_validate(
        first.target.model_dump()
        | {
            "provider": "google",
            "api_family": "google_generate_content",
            "model_id": "gemini-3.5-flash-lite",
            "registry_id": "google-qualification",
            "endpoint_id": "google.official.v1",
            "context_window": 1_048_576,
            "max_output_tokens": 65_536,
        }
    )
    target_hashes = tuple(sorted({canonical_sha256(first.target), canonical_sha256(target)}))
    first = first.model_copy(update={"qualification_target_sha256s": target_hashes})
    second = QualificationRecipe.model_validate(
        first.model_dump(by_alias=True)
        | {
            "recipe_id": "google-case",
            "target": target,
            "financial_input_ceiling": 1_048_576,
            "financial_output_ceiling": 65_536,
        }
    )
    service = QualificationPreparationService(rows.factory, (first, second))
    with pytest.raises(ValueError):
        QualificationPreparationService(
            rows.factory,
            (first, second.model_copy(update={"registry_revision": "different-registry"})),
        )
    before = await service.prepare_qualification(scope, identity, first.recipe_id)
    after = await service.prepare_qualification(scope, identity, second.recipe_id)
    assert before.work.registration == after.work.registration
    assert before.request.action_id != after.request.action_id
    assert len(rows.actions) == 2
    assert sum(isinstance(row, RegisteredWork) for row in rows.added) == 1
    assert sum(isinstance(row, ExecutionWork) for row in rows.added) == 1
    # Removing/replacing the declared target set cannot mint an alternative root.
    with pytest.raises(ValueError):
        await QualificationPreparationService(rows.factory, (first,)).prepare_qualification(
            scope, identity, first.recipe_id
        )
