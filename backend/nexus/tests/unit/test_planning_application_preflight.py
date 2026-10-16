"""Preflight gate ordering with supplied native rows; no SQL, key or SDK qualification."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import jwt
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.directory_models import DirectoryMembership
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.planning_native_facts import read_end
from nexus.execution import planning_application_preflight as module
from nexus.execution.planning_application import PlanningApplication, compose_planning_application
from nexus.execution.qualification_application import FiniteWorkerCredential
from nexus.harness.journal_models import CompanyControl
from nexus.tests.unit.planning_application_fixture import configuration
from nexus.tests.unit.test_planning_application import TEST_SIGNER, application_settings


def prepared(root: Path, *, wrong_actor: bool = False) -> PlanningApplication:
    config = configuration(root)
    actor = config.admission.slots[0].child.binding
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(
                config.admission.procedure.binding.actor_id if wrong_actor else actor.actor_id
            ),
            "workspace_id": str(actor.workspace_id),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        TEST_SIGNER,
        algorithm="HS256",
    )
    return compose_planning_application(
        async_sessionmaker[AsyncSession](),
        config,
        application_settings(),
        FiniteWorkerCredential(SecretStr(token)),
        SecretStr(TEST_SIGNER),
    )


def native_rows(
    app: PlanningApplication,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fault: str | None = None,
) -> list[str]:
    """Supply only native IO leaves; exercise the real preflight orchestration and predicates."""
    config, events = app.config, []
    owner = config.admission.procedure.binding.actor_id
    control = CompanyControl(
        company_id=config.goal.company_id,
        owner_id=owner,
        policy_version=config.policy_version,
        price_version=config.catalog.models.pricebook_version,
        paused=False,
        daily_cap_usd=Decimal(5),
        work_cap_usd=Decimal(1),
    )
    if fault == "cap":
        control.daily_cap_usd = Decimal(6)
    elif fault == "pause":
        control.paused = True
    elif fault == "policy":
        control.policy_version = "different-current-policy"
    elif fault == "price":
        control.price_version = "different-current-price"
    session = AsyncMock(spec=AsyncSession)
    member = DirectoryMembership(
        company_id=config.goal.company_id,
        principal_id=owner,
        role="owner",
        principal_active=fault != "owner",
        membership_active=True,
    )
    session.get.return_value = member

    @asynccontextmanager
    async def transaction(
        factory: async_sessionmaker[AsyncSession],
        scope: BrainReadScope,
        identity: VerifiedIdentity,
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
        assert factory is app.runtime.factory
        assert scope.task_id is None and scope.task_trace_id is None and scope.actor_id is None
        assert (scope.principal_id, scope.workspace_id) == (
            config.admission.slots[0].child.binding.actor_id,
            config.admission.slots[0].child.binding.workspace_id,
        )
        assert identity.principal_id == scope.principal_id
        events.append("native")
        yield cast(AsyncSession, session), control, datetime.now(UTC)

    async def charter(*args: object) -> SimpleNamespace:
        events.append("charter")
        return SimpleNamespace(mandate=config.admission.mandate, recorded_by=owner)

    monkeypatch.setattr(module, "brain_transaction", transaction)
    monkeypatch.setattr(module, "preflight_qualification_database", AsyncMock())
    monkeypatch.setattr(
        GoalStore,
        "_current",
        AsyncMock(
            return_value=SimpleNamespace(
                definition=SimpleNamespace(owner_id=owner, mandate=config.admission.mandate),
            )
        ),
    )
    monkeypatch.setattr(
        module,
        "current_mandate",
        AsyncMock(
            return_value=SimpleNamespace(
                mandate=SimpleNamespace(
                    owner_id=owner,
                    oversight="supervised",
                    self_improvement_enabled=False,
                    work_cap_usd=Decimal(1),
                    daily_cap_usd=Decimal(5),
                    goals=(config.goal.goal_id,),
                ),
            )
        ),
    )
    monkeypatch.setattr(module, "current_charter", charter)
    monkeypatch.setattr(module, "require_brain_scope", AsyncMock())
    monkeypatch.setattr(
        module, "db_clock", AsyncMock(side_effect=lambda session: datetime.now(UTC))
    )
    return events


async def test_bootstrap_preflight_uses_actual_unbound_actor_before_any_work_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = prepared(tmp_path)
    events = native_rows(app, monkeypatch)
    await module.preflight_planning_application(app, end_us=read_end())
    assert events == ["native", *(["charter"] * 6), "native", *(["charter"] * 6)]
    assert not app.runtime._operations and not app.lifecycle.pending_owners()


@pytest.mark.parametrize("fault", ["cap", "pause", "policy", "price", "owner"])
async def test_native_denial_precedes_worker_key_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    app = prepared(tmp_path)
    native_rows(app, monkeypatch, fault=fault)
    resolver = AsyncMock(side_effect=AssertionError("Provider key read before native denial"))
    monkeypatch.setattr(type(app.runtime.resolver), "resolve", resolver)
    with pytest.raises(ValueError):
        await module.preflight_planning_application(
            app, end_us=read_end(), require_provider_keys=True
        )
    resolver.assert_not_awaited()


async def test_wrong_actual_actor_denied_before_database_or_key_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = prepared(tmp_path, wrong_actor=True)
    database = AsyncMock(side_effect=AssertionError("Wrong actor reached database"))
    monkeypatch.setattr(module, "preflight_qualification_database", database)
    with pytest.raises(ValueError, match="actual actor"):
        await module.preflight_planning_application(app, end_us=read_end())
    database.assert_not_awaited()


async def test_worker_resolves_only_selected_endpoint_after_native_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = prepared(tmp_path)
    events = native_rows(app, monkeypatch)

    async def resolve(endpoint_id: str) -> None:
        assert endpoint_id == app.config.catalog.models.models[0].endpoint_id
        assert events == ["native", *(["charter"] * 6)]
        events.append("key-availability")

    monkeypatch.setattr(type(app.runtime.resolver), "resolve", staticmethod(resolve))
    await module.preflight_planning_application(app, end_us=read_end(), require_provider_keys=True)
    assert events == [
        "native",
        *(["charter"] * 6),
        "key-availability",
        "native",
        *(["charter"] * 6),
    ]


async def test_minimal_boot_does_not_require_fresh_actor_native_goal_or_provider_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.settings import settings
    from nexus.tests.unit.test_planning_application import SuppliedCredential

    provider = SuppliedCredential()
    app = compose_planning_application(
        async_sessionmaker[AsyncSession](),
        configuration(tmp_path),
        application_settings(),
        provider,
        SecretStr(TEST_SIGNER),
    )
    monkeypatch.setattr(settings, "jwt_secret_key", TEST_SIGNER)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    native = AsyncMock(side_effect=AssertionError("Boot read fresh native Goal/authority"))
    key = AsyncMock(side_effect=AssertionError("Boot read provider credential"))
    database = AsyncMock()
    monkeypatch.setattr(module, "_native", native)
    monkeypatch.setattr(type(app.runtime.resolver), "resolve", key)
    monkeypatch.setattr(module, "preflight_qualification_database", database)
    await module.preflight_planning_database(app, end_us=read_end())
    database.assert_awaited_once()
    native.assert_not_awaited()
    key.assert_not_awaited()
    assert provider.reads == 0
