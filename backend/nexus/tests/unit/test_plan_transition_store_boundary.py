"""Real store entry must deny configured full transition before writes without native proof ABI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.transactions import ManagementDeniedError
from nexus.tests.unit.cycle_admission_fixture import declared
from nexus.tests.unit.cycle_full_structural_support import configured
from nexus.tests.unit.test_plan_choice_wire_integration import selection


@pytest.mark.parametrize("chosen", [False, True])
async def test_real_full_propose_never_reaches_write_without_concrete_owner_proof(
    chosen: bool,
) -> None:
    data = configured()
    catalog = data.catalog.model_copy(update={"cycle_admission": data.admission})
    store = ManagementPlanStore(MagicMock(), catalog)
    bound = data.admission.procedure.binding
    scope = CompanyControlScope(
        company_id=data.admission.company_id,
        principal_id=bound.actor_id,
        operation_id=UUID(int=800),
        trace_id=UUID(int=801),
    )
    identity = VerifiedIdentity(principal_id=bound.actor_id, workspace_id=bound.workspace_id)
    session = MagicMock()
    control = MagicMock(owner_id=bound.actor_id)

    @asynccontextmanager
    async def transaction(*args: object, **kwargs: object) -> AsyncIterator[tuple[Any, Any, None]]:
        # Async context-manager test harness supplies only the storage transaction boundary.
        yield session, control, None

    write = AsyncMock(side_effect=AssertionError("Unqualified full plan reached proposal write"))
    payload = declared(data.admission, 2)
    if chosen:
        payload = payload.model_copy(update={"strategy_selection": selection()})
    with (
        patch("nexus.company.management.plan_store.management_owner_transaction", transaction),
        patch("nexus.company.management.plan_store.require_plan_not_cancelled", AsyncMock()),
        patch("nexus.company.management.plan_store.validate_plan", AsyncMock(return_value={})),
        patch(
            "nexus.company.management.plan_store.db_clock",
            AsyncMock(return_value=datetime(2026, 10, 15, tzinfo=UTC)),
        ),
        patch("nexus.company.management.plan_store.propose_locked", write),
        pytest.raises(ManagementDeniedError),
    ):
        await store.propose(scope, identity, payload, expected_current_revision_id=None)
    write.assert_not_awaited()
