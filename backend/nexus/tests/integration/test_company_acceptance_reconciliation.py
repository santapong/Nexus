"""Known native check receipts may recover proof without republishing or resetting allowance."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.acceptance_evidence import ProtectedReportEvidenceResolver
from nexus.company.management.acceptance_recovery import AcceptanceRecovery
from nexus.tests.generated_artifact_fixture import ledger
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.native_workflow_support import known_check
from nexus.tests.native_workflow_support import workflow_factory as workflow_factory


async def test_known_actual_check_receipt_reconciles_acceptance_with_exact_replay(
    workflow_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await known_check(workflow_factory, tmp_path)
    verifier = case.scenario.payload.children[1].binding
    original = await case.scenario.execution.release(
        case.original_lease, identity(verifier.actor_id)
    )
    lease = await case.scenario.execution.recover_dispatched(
        ledger(verifier),
        identity(verifier.actor_id),
        uuid4(),
        case.command.segment_id,
    )
    assert lease.mode == "reconcile"
    store = AcceptanceRecovery(
        workflow_factory,
        ProtectedReportEvidenceResolver(
            case.scenario.artifacts,
            case.scenario.producer.inputs,
            case.scenario.publisher.freshness,
        ),
        case.scenario.producer,
    )
    accepted = await store.reconcile_verified_result(
        lease, identity(verifier.actor_id), check_action_id=case.action.action_id
    )
    assert accepted.verdict == "pass"
    assert accepted.target.action_id == case.scenario.action.action_id
    assert (
        await store.reconcile_verified_result(
            lease, identity(verifier.actor_id), check_action_id=case.action.action_id
        )
        == accepted
    )
    after = await case.scenario.execution.get(ledger(verifier), identity(verifier.actor_id))
    assert after.counters == original.counters and after.delegated == original.delegated
    assert after.segment_number == original.segment_number


async def test_author_receipt_or_unknown_check_selector_cannot_publish_recovered_proof(
    workflow_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await known_check(workflow_factory, tmp_path)
    verifier = case.scenario.payload.children[1].binding
    await case.scenario.execution.release(case.original_lease, identity(verifier.actor_id))
    lease = await case.scenario.execution.recover_dispatched(
        ledger(verifier), identity(verifier.actor_id), uuid4(), case.command.segment_id
    )
    store = AcceptanceRecovery(
        workflow_factory,
        ProtectedReportEvidenceResolver(
            case.scenario.artifacts,
            case.scenario.producer.inputs,
            case.scenario.publisher.freshness,
        ),
        case.scenario.producer,
    )
    for wrong in (case.scenario.action.action_id, uuid4()):
        with pytest.raises(ValueError):
            await store.reconcile_verified_result(
                lease, identity(verifier.actor_id), check_action_id=wrong
            )
