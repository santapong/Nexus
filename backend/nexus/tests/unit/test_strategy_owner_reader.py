"""Owner wrapper keeps actual owner scope and rechecks it after the concrete proof read."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.strategy import owner_reader as module
from nexus.company.strategy.owner_reader import StrategyOwnerProofReader
from nexus.harness.journal_models import CompanyControl
from nexus.tests.unit.strategy_current_proof_fixture import ProofCase, proof_case


def install_transaction(case: ProofCase, monkeypatch: pytest.MonkeyPatch) -> CompanyControlScope:
    scope = CompanyControlScope(
        company_id=case.scope.company_id,
        principal_id=case.scope.principal_id,
        operation_id=case.scope.operation_id,
        trace_id=case.scope.trace_id,
    )

    @asynccontextmanager
    async def owner_transaction(
        factory: object, requested: CompanyControlScope, identity: VerifiedIdentity
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, object]]:
        assert requested == scope and identity == case.credential.identity
        assert factory is case.base.reader.artifacts.factory
        yield case.session, case.base.source.control, case.base.source.clock["now"]

    monkeypatch.setattr(module, "management_owner_transaction", owner_transaction)
    return scope


async def test_owner_wrapper_uses_real_taskless_scope_and_returns_no_choice_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = proof_case(monkeypatch)
    scope = install_transaction(case, monkeypatch)
    wrapper = StrategyOwnerProofReader(case.base.reader.artifacts.factory, case.service)
    result = await wrapper.load(
        scope, case.credential.identity, case.selection, credential=case.credential
    )
    assert result.selection == case.selection
    assert case.scope.principal_id == case.base.source.control.owner_id
    case.session.add.assert_not_called()
    case.session.flush.assert_not_called()
    case.session.commit.assert_not_called()


async def test_owner_wrapper_checks_current_membership_after_proof_await(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = proof_case(monkeypatch)
    scope = install_transaction(case, monkeypatch)
    wrapper = StrategyOwnerProofReader(case.base.reader.artifacts.factory, case.service)
    original = case.service.load_locked

    async def read(*args: object, **kwargs: object) -> object:
        result = await original(*args, **kwargs)  # type: ignore[arg-type]
        case.member.membership_active = False
        return result

    monkeypatch.setattr(case.service, "load_locked", AsyncMock(side_effect=read))
    with pytest.raises(BrainDeniedError):
        await wrapper.load(
            scope, case.credential.identity, case.selection, credential=case.credential
        )
    assert case.graph_calls == {"B/S": 2, "C": 2}


async def test_bare_verified_identity_does_not_substitute_for_signed_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = proof_case(monkeypatch)
    with pytest.raises(AcceptanceDeniedError):
        await case.service.load_locked(
            case.session,
            case.base.source.control,
            case.scope,
            case.credential.identity,
            case.selection,
            credential=case.credential.identity,  # type: ignore[arg-type]
        )
    assert case.body_gets == []


def test_owner_wrapper_cannot_mix_factory_or_unconfigured_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = proof_case(monkeypatch)
    wrong = cast(async_sessionmaker[AsyncSession], object())
    with pytest.raises(AcceptanceDeniedError):
        StrategyOwnerProofReader(wrong, case.service)
    with pytest.raises(AcceptanceDeniedError):
        StrategyOwnerProofReader(wrong, object())  # type: ignore[arg-type]
