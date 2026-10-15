"""Lower actual SV facts can be read by real owner identity; never by an invented SV lease."""

import asyncio
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from pydantic import SecretStr

from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.notifications.worker_identity import WorkerIdentityDeniedError, _verify
from nexus.company.strategy import verifier_facts as module
from nexus.company.strategy.verifier_facts import require_strategy_verifier_facts_locked
from nexus.execution.runtime_models import ExecutionWork
from nexus.tests.unit.strategy_current_proof_fixture import ProofCase, proof_case
from nexus.tests.unit.strategy_verifier_receipt_fixture import receipt_case


async def facts(case: ProofCase) -> object:
    return await require_strategy_verifier_facts_locked(
        case.session,
        case.base.source.control,
        case.scope,
        case.credential.identity,
        case.pair.verifier,
        case.record.target,
        verifier_action_id=case.verifier.action.action_id,
        protected_result=case.verifier.protected_result,
        rule=case.base.reader.rules.check,
        artifacts=case.base.reader.artifacts,
        credential=case.credential,
    )


@pytest.mark.parametrize("fence", [0, -1, True, 3.0, "3"])
async def test_current_work_fence_is_real_nonzero_literal_integer(
    monkeypatch: pytest.MonkeyPatch, fence: object
) -> None:
    case = proof_case(monkeypatch)
    case.pair.verifier.fence = fence
    with pytest.raises(AcceptanceDeniedError):
        await facts(case)
    assert case.body_gets == []


async def test_current_owner_reads_actual_original_sv_facts_without_sv_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = proof_case(monkeypatch)
    assert case.pair.verifier.lease_until is None
    result = await facts(case)
    assert result == case.verifier
    call = cast(AsyncMock, case.base.reader.artifacts.revalidate_artifact_reference).await_args
    assert call is not None
    assert call.args[2] == case.scope and call.args[3] == case.credential.identity
    assert case.scope.principal_id != case.record.target.verifier.actor_id


async def test_an_unregistered_work_instance_cannot_supply_current_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = proof_case(monkeypatch)
    fake = ExecutionWork(
        company_id=case.scope.company_id, task_id=case.record.target.verifier.task_id
    )
    with pytest.raises(AcceptanceDeniedError):
        await require_strategy_verifier_facts_locked(
            case.session,
            case.base.source.control,
            case.scope,
            case.credential.identity,
            fake,
            case.record.target,
            verifier_action_id=case.verifier.action.action_id,
            protected_result=case.verifier.protected_result,
            rule=case.base.reader.rules.check,
            artifacts=case.base.reader.artifacts,
            credential=case.credential,
        )
    assert case.body_gets == []


async def test_wrong_c_metadata_resource_denies_before_body_and_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = proof_case(monkeypatch)
    cast(AsyncMock, case.base.reader.artifacts.revalidate_artifact_reference).reset_mock()
    ref = case.verifier.protected_result
    metadata = MagicMock()
    metadata.one_or_none.return_value = (
        ref.artifact_id,
        ref.artifact_revision_id,
        ref.revision,
        ref.sha256,
        ref.byte_length,
        case.record.target.company_id,
    )
    case.session.execute = AsyncMock(return_value=metadata)
    with pytest.raises(AcceptanceDeniedError):
        await facts(case)
    assert case.body_gets == []
    cast(AsyncMock, case.base.reader.artifacts.revalidate_artifact_reference).assert_not_awaited()


async def test_signature_verified_credential_expiring_during_actual_read_await_denies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = receipt_case(monkeypatch)
    key = SecretStr("public-synthetic-lower-receipt-expiry-test-key-at-least64-characters")
    expiry = int(datetime.now(UTC).timestamp()) + 2
    credential = _verify(
        SecretStr(
            jwt.encode(
                {
                    "sub": str(case.lease.actor_id),
                    "workspace_id": str(case.lease.workspace_id),
                    "iat": expiry - 3,
                    "exp": expiry,
                },
                key.get_secret_value(),
                algorithm="HS256",
            )
        ),
        key,
    )
    nominated = []

    async def read(*_: object) -> None:
        nominated.append(datetime.now(UTC))
        await asyncio.sleep(
            max(0, credential.expires_at.timestamp() - datetime.now(UTC).timestamp()) + 0.02
        )

    async def now(*_: object) -> datetime:
        return datetime.now(UTC)

    monkeypatch.setattr(module, "db_now", now)
    case.artifacts.revalidate_artifact_reference = AsyncMock(side_effect=read)
    from nexus.company.strategy.publication_protection import strategy_publication_scope

    with pytest.raises(WorkerIdentityDeniedError):
        await require_strategy_verifier_facts_locked(
            case.session,
            case.control,
            strategy_publication_scope(case.lease, case.action.action_id),
            credential.identity,
            case.work,
            case.target,
            verifier_action_id=case.action.action_id,
            protected_result=case.reference,
            rule=case.rule,
            artifacts=case.artifacts,
            credential=credential,
        )
    assert len(nominated) == 1 and nominated[0] < credential.expires_at <= datetime.now(UTC)


async def test_original_sv_attempt_cannot_precede_action_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import timedelta

    from nexus.execution.runtime_models import ExecutionAttempt

    case = proof_case(monkeypatch)
    action = case.verifier.action.action_id
    attempt = case.base.rows[
        (ExecutionAttempt, (case.scope.company_id, case.record.target.verifier.task_id, action))
    ]
    attempt.reserved_at -= timedelta(seconds=1)  # type: ignore[attr-defined]
    with pytest.raises(AcceptanceDeniedError):
        await facts(case)
