"""Original owner windows over supplied existing validation/metadata SQL delivery; no DB proof."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.contained_query import clock_us
from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.nexus_plan_admission import (
    capture_nexus_owner_locked,
    finish_nexus_owner_locked,
    require_nexus_exit,
)
from nexus.company.management.plan_admission_candidates import capture_child_window
from nexus.company.management.plan_admission_window import PlanAdmissionWindow, PlanGrantWindow
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import PlanPayload
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.harness.journal_models import CompanyControl
from nexus.tests.unit.nexus_cycle_fixture import case, key
from nexus.tests.unit.nexus_report_fixture import credentials


async def setup(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    ManagementPlanStore,
    AsyncSession,
    CompanyControl,
    CompanyControlScope,
    VerifiedIdentity,
    PlanPayload,
    AuthenticatedWorkerIdentity,
    SimpleNamespace,
    AsyncMock,
]:
    from nexus.company.management import nexus_plan_admission as module

    admission, catalog = case()
    payload = admission.payload("planning")
    factory = MagicMock()
    freshness = RegisteredSourceFreshness(factory, MagicMock())
    store = ManagementPlanStore(factory, catalog, source_freshness=freshness)
    credential = await credentials(admission.procedure.binding).current(admission.procedure.binding)
    identity = credential.identity
    scope = CompanyControlScope(
        company_id=admission.company_id,
        principal_id=identity.principal_id,
        operation_id=key("owner-operation"),
        trace_id=key("owner-trace"),
    )
    control = CompanyControl(
        company_id=scope.company_id,
        owner_id=identity.principal_id,
        policy_version="p1",
        price_version="p1",
        paused=False,
        work_cap_usd=admission.procedure.allocation_usd,
        daily_cap_usd=admission.procedure.allocation_usd,
    )
    mock = MagicMock(spec=AsyncSession)
    mock.scalar = AsyncMock(return_value=None)
    mock.get = AsyncMock(return_value=None)
    state = SimpleNamespace(
        now=datetime.now(UTC), grant_end=datetime.now(UTC) + timedelta(seconds=10)
    )
    validate = AsyncMock(return_value={})
    monkeypatch.setattr(module, "validate_plan", validate)

    async def metadata(*args: object, **kwargs: object) -> PlanAdmissionWindow:
        return PlanAdmissionWindow(
            scope.company_id,
            control.owner_id,
            identity.workspace_id,
            canonical_sha256(payload),
            canonical_sha256(catalog),
            "p1",
            "p1",
            state.now,
            (capture_child_window(catalog, payload.children[0], state.now),),
            (PlanGrantWindow(key("resource"), identity.principal_id, 1, 1, state.grant_end),),
            (),
            None,
            None,
            credential,
        )

    monkeypatch.setattr(module, "_capture_plan_metadata_locked", metadata)
    monkeypatch.setattr(module, "db_clock", AsyncMock(side_effect=lambda _: state.now))
    return (
        store,
        cast(AsyncSession, mock),
        control,
        scope,
        identity,
        payload,
        credential,
        state,
        validate,
    )


async def test_actual_genuine_owner_witness_and_original_window_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, session, control, scope, identity, payload, witness, _state, validate = await setup(
        monkeypatch
    )
    first = await capture_nexus_owner_locked(
        store, session, control, scope, identity, payload, witness, end_us=clock_us() + 30_000_000
    )
    assert first is not None and first.captured.window.credential is witness
    await finish_nexus_owner_locked(
        store, session, control, scope, identity, payload, witness, first
    )
    require_nexus_exit(first)
    assert validate.await_count == 2


@pytest.mark.parametrize("fault", ["missing", "wrong-owner", "expired"])
async def test_bad_witness_denied_before_any_validated_plan_data_read(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    store, session, control, scope, identity, payload, witness, state, validate = await setup(
        monkeypatch
    )
    if fault == "wrong-owner":
        control.owner_id = key("other-owner")
    if fault == "expired":
        state.now = witness.expires_at
    with pytest.raises(ValueError):
        await capture_nexus_owner_locked(
            store,
            session,
            control,
            scope,
            identity,
            payload,
            None if fault == "missing" else witness,
            end_us=clock_us() + 30_000_000,
        )
    validate.assert_not_awaited()


async def test_later_renewed_grant_cannot_rescue_the_first_expired_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, session, control, scope, identity, payload, witness, state, _ = await setup(monkeypatch)
    first = await capture_nexus_owner_locked(
        store, session, control, scope, identity, payload, witness, end_us=clock_us() + 30_000_000
    )
    assert first is not None
    state.now = state.grant_end + timedelta(microseconds=1)
    state.grant_end = state.now + timedelta(minutes=1)
    with pytest.raises(ValueError):
        await finish_nexus_owner_locked(
            store, session, control, scope, identity, payload, witness, first
        )


async def test_same_value_replacement_store_catalog_is_not_original_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, session, control, scope, identity, payload, witness, _state, _ = await setup(monkeypatch)
    first = await capture_nexus_owner_locked(
        store, session, control, scope, identity, payload, witness, end_us=clock_us() + 30_000_000
    )
    store.catalog = store.catalog.model_copy()
    with pytest.raises(ValueError):
        await finish_nexus_owner_locked(
            store, session, control, scope, identity, payload, witness, first
        )
