"""Concrete lifecycle and native-row loader controls; supplied rows do not qualify SQL or models."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid5

import jwt
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanHead,
    ManagementPlanRevision,
    ManagementProcedure,
)
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.management.planning_native_facts import clock_us
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    NotificationWorkerIdentities,
)
from nexus.execution import planning_lifecycle as module
from nexus.execution.planning_application import compose_planning_application
from nexus.execution.planning_lifecycle import PlanningLifecycle
from nexus.execution.planning_lifecycle_bindings import PlanningBundle, approved_bundle
from nexus.harness.journal_models import CompanyControl
from nexus.settings import Settings
from nexus.tests.unit.planning_application_fixture import configuration
from nexus.tests.unit.test_company_auth import TEST_KEY


def lifecycle_case(root: Path) -> PlanningLifecycle:
    """Real full composition with synthetic signed actor source, never a fabricated native base."""
    config = configuration(root)
    actor = config.admission.slots[0].child.binding

    class Credentials:
        async def credential(self) -> SecretStr:
            now = datetime.now(UTC)
            return SecretStr(
                jwt.encode(
                    {
                        "sub": str(actor.actor_id),
                        "workspace_id": str(actor.workspace_id),
                        "iat": int((now - timedelta(seconds=1)).timestamp()),
                        "exp": int((now + timedelta(minutes=5)).timestamp()),
                    },
                    TEST_KEY,
                    algorithm="HS256",
                )
            )

    factory = async_sessionmaker[AsyncSession]()
    return compose_planning_application(
        factory, config, Settings(jwt_secret_key=TEST_KEY), Credentials(), SecretStr(TEST_KEY)
    ).lifecycle


async def witness(
    lifecycle: PlanningLifecycle, *, foreign: bool = False
) -> AuthenticatedWorkerIdentity:
    owner = lifecycle.config.admission.procedure.binding

    class Credentials:
        async def credential(self) -> SecretStr:
            now = datetime.now(UTC)
            return SecretStr(
                jwt.encode(
                    {
                        "sub": str(UUID(int=999) if foreign else owner.actor_id),
                        "workspace_id": str(owner.workspace_id),
                        "iat": int((now - timedelta(seconds=1)).timestamp()),
                        "exp": int((now + timedelta(minutes=5)).timestamp()),
                    },
                    TEST_KEY,
                    algorithm="HS256",
                )
            )

    return await NotificationWorkerIdentities(
        Credentials(), SecretStr(TEST_KEY), enabled=True
    ).current()


def scope(lifecycle: PlanningLifecycle) -> CompanyControlScope:
    config = lifecycle.config
    return CompanyControlScope(
        company_id=config.admission.company_id,
        principal_id=config.admission.procedure.binding.actor_id,
        operation_id=uuid5(config.goal.goal_id, "owner-operation"),
        trace_id=uuid5(config.goal.goal_id, "owner-trace"),
    )


async def native_bundle(
    lifecycle: PlanningLifecycle, monkeypatch: pytest.MonkeyPatch, *, fault: str | None = None
) -> PlanningBundle:
    """Actual typed native row/header reconstruction with only SQL transport supplied."""
    config, now = lifecycle.config, datetime.now(UTC)
    admission = config.admission
    payload = admission.payload("planning")
    digest = canonical_sha256(payload)
    revision_id = uuid5(admission.plan_id, f"plan:1:{digest}")
    decision_id = uuid5(revision_id, "owner:approve")
    owner_id = admission.procedure.binding.actor_id
    row = ManagementPlanRevision(
        company_id=admission.company_id,
        plan_id=admission.plan_id,
        plan_revision_id=revision_id,
        revision=1,
        goal_id=config.goal.goal_id,
        goal_revision_id=config.goal.revision_id,
        mandate_revision_id=admission.mandate.revision_id,
        sha256=digest,
        snapshot_json=payload.model_dump_json(),
        proposed_by=owner_id,
        recorded_at=now,
    )
    decision = ManagementOwnerDecision(
        company_id=admission.company_id,
        decision_id=decision_id,
        plan_revision_id=revision_id,
        owner_id=owner_id,
        kind="approve",
        payload_sha256=digest,
        recorded_at=now,
    )
    head = ManagementPlanHead(
        company_id=admission.company_id,
        plan_id=admission.plan_id,
        current_revision_id=revision_id,
        goal_id=config.goal.goal_id,
        state="approved",
        decision_id=decision_id,
    )
    root = admission.procedure
    procedure = ManagementProcedure(
        company_id=admission.company_id,
        procedure_id=root.procedure_id,
        goal_id=config.goal.goal_id,
        parent_task_id=root.binding.task_id,
        parent_run_id=root.binding.run_id,
        allocation_usd=root.allocation_usd,
        quota_json=root.quota.model_dump_json(),
        binding_json=root.binding.model_dump_json(),
    )
    if fault == "approval":
        decision.payload_sha256 = "f" * 64
    elif fault == "owner":
        decision.owner_id = UUID(int=999)
    elif fault == "head":
        head.state = "revoked"
    elif fault == "payload":
        row.sha256 = "f" * 64
    elif fault == "root":
        procedure.allocation_usd += 1
    fake = MagicMock(spec=AsyncSession)
    rows: dict[type[object], object] = {
        ManagementPlanHead: head,
        ManagementOwnerDecision: decision,
        ManagementProcedure: procedure,
    }
    fake.get = AsyncMock(side_effect=lambda model, key: rows.get(model))

    async def scalars(statement: object) -> object:
        # SQL delivery only; actual production row decoder and all joins remain in use.
        result = MagicMock()
        entity = cast(MagicMock, statement).column_descriptions[0]["entity"]
        result.all.return_value = (
            [row]
            if entity is ManagementPlanRevision
            else ([] if fault == "missing" else [decision])
        )
        return result

    fake.scalars = AsyncMock(side_effect=scalars)
    slot = admission.slots[0]
    current = CurrentPlanBinding(
        company_id=admission.company_id,
        plan=PlanRevision(
            company_id=admission.company_id,
            plan_id=admission.plan_id,
            plan_revision_id=revision_id,
            revision=1,
            sha256=digest,
            payload=payload,
            proposed_by=owner_id,
            recorded_at=now,
        ),
        child=slot.child,
        work=slot.work,
        work_sha256="a" * 64,
        procedure_id=root.procedure_id,
    )
    if fault == "child":
        current = current.model_copy(update={"child": admission.slots[1].child})
    monkeypatch.setattr(ManagementPlanStore, "current_binding", AsyncMock(return_value=current))
    return await approved_bundle(
        cast(AsyncSession, fake),
        CompanyControl(company_id=admission.company_id, owner_id=owner_id),
        config,
        lifecycle.services,
    )


def test_real_lifecycle_composition_captures_config_and_input_graph(tmp_path: Path) -> None:
    from typing import get_type_hints

    from nexus.company.management.api_services import ManagementApiServices
    from nexus.execution.planning_owner_reads import PlanningApiServices

    value = lifecycle_case(tmp_path)
    value.require_composition()
    assert not value.pending_owners()
    assert get_type_hints(ManagementApiServices)["planning_lifecycle"]
    assert get_type_hints(PlanningApiServices)["lifecycle"]
    value.config = value.config.model_copy(update={"registry_id": "crossed"})
    with pytest.raises(ValueError, match="composition"):
        value.require_composition()


@pytest.mark.parametrize(
    "fault", [None, "missing", "approval", "owner", "head", "payload", "root", "child"]
)
async def test_actual_native_r1_approval_payload_root_and_child_are_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str | None,
) -> None:
    value = lifecycle_case(tmp_path)
    if fault is not None:
        with pytest.raises(ValueError):
            await native_bundle(value, monkeypatch, fault=fault)
    else:
        bundle = await native_bundle(value, monkeypatch)
        assert bundle.base.payload == value.config.admission.payload("planning")
        assert bundle.plans.planning_reader is bundle.reader
        bundle.require_composition()


async def test_prepare_uses_actual_configured_actor_and_never_owner_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = lifecycle_case(tmp_path)
    owner = await witness(value)
    bundle = await native_bundle(value, monkeypatch)
    monkeypatch.setattr(value, "_bundle", AsyncMock(return_value=(bundle, clock_us() + 30_000_000)))
    native = AsyncMock(side_effect=ValueError("existing native stop"))
    monkeypatch.setattr(module, "prepare_work", native)
    with pytest.raises(ValueError, match="existing native stop"):
        await value.prepare(
            scope(value),
            owner,
            value.config.goal,
            bundle.base.plan_revision_id,
            end_us=clock_us() + 30_000_000,
        )
    assert native.await_args is not None
    actual_scope = native.await_args.args[1]
    actor = await value.services.identities.current()
    assert actual_scope.principal_id == actor.identity.principal_id
    assert actual_scope.principal_id != owner.identity.principal_id
    native.assert_awaited_once()
    native.reset_mock()
    with pytest.raises(ValueError, match="r1 CAS"):
        await value.prepare(
            scope(value), owner, value.config.goal, UUID(int=999), end_us=clock_us() + 30_000_000
        )
    native.assert_not_awaited()


async def test_expired_original_end_denies_before_native_prepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = lifecycle_case(tmp_path)
    owner = await witness(value)
    native = AsyncMock()
    monkeypatch.setattr(module, "prepare_work", native)
    with pytest.raises(TimeoutError):
        await value.prepare(scope(value), owner, value.config.goal, None, end_us=clock_us() - 1)
    native.assert_not_awaited()
