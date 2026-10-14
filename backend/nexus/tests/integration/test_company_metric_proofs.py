"""Unavailable current independent proof is unknown; a candidate never counts as acceptance."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
from nexus.company.contracts.results import VerificationResult
from nexus.company.management.check_contracts import REPORT_CHECK_CRITERIA
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_metrics import metrics_factory as metrics_factory
from nexus.tests.metric_fixture import (
    accept_report,
    configured_metric,
    issue_native,
    prepared_author,
)


async def test_receipt_and_raw_candidate_pass_do_not_count_as_independent_acceptance(
    metrics_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await configured_metric(metrics_factory, tmp_path)
    prepared, parameters = await prepared_author(metrics_factory, case)
    author, verifier = (row.binding for row in case.payload.children)
    action, lease, _ = await issue_native(
        metrics_factory,
        case,
        author,
        prepared,
        parameters,
        case.publisher.rules["company.report.write.v1"],
    )
    await case.effects.record_verification_candidate(
        lease,
        identity(author.actor_id),
        VerificationResult(
            company_id=COMPANY,
            verification_id=uuid4(),
            action_id=action.action_id,
            verifier_id=verifier.actor_id,
            verdict="pass",
            criterion_ids=REPORT_CHECK_CRITERIA,
            evidence_ids=(uuid4(),),
        ),
    )
    record = await case.store.observe(control(), identity(OWNER), case.request)
    assert record.snapshot.comparison.value.kind == "known"
    assert record.snapshot.comparison.value.value == 0
    assert record.snapshot.work[0].acceptance_id is None
    await case.execution.release(lease, identity(author.actor_id))


async def test_claimed_pass_after_owner_source_revoke_is_unknown_and_history_denies(
    metrics_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await configured_metric(metrics_factory, tmp_path)
    await accept_report(metrics_factory, case)
    record = await case.store.observe(control(), identity(OWNER), case.request)
    assert record.snapshot.comparison.value.kind == "known"
    async with management_owner_transaction(metrics_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        grant = await session.get(BrainResourceAccess, (COMPANY, RESOURCE, OWNER))
        assert grant is not None
        resource = await session.get(BrainResource, (COMPANY, RESOURCE))
        assert resource is not None
        generation = resource.acl_generation
    await ResourceAccessStore(metrics_factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            principal_id=OWNER,
            active=False,
            expected_generation=generation,
        ),
    )
    current = await case.store.current(control(), identity(OWNER), record.observation_id)
    assert current is not None and current.snapshot.comparison.value.kind == "unknown"
    assert current.comparison_result == "unknown" and not current.snapshot.sources
    assert not current.snapshot.work[0].artifacts
    with pytest.raises(ManagementDeniedError):
        await case.store.get_saved(control(), identity(OWNER), record.observation_id)
    changed = case.request.model_copy(update={"observation_id": uuid4()})
    new = await case.store.observe(
        control().model_copy(update={"operation_id": uuid4(), "trace_id": uuid4()}),
        identity(OWNER),
        changed,
    )
    assert new.snapshot.comparison.value.kind == "unknown"
    assert new.snapshot.comparison.result == "unknown"
