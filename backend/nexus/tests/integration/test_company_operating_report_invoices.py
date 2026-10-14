"""Public owner billing retains private proof ACL in every shareable report manifest."""

from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.management.operation_models import ManagementReportSnapshot
from nexus.execution.billing_models import BillingEvidence
from nexus.harness.journal_models import CostHold
from nexus.tests.integration.management_acceptance_source_fixture import Policies
from nexus.tests.integration.operating_report_fixture import configured_report, loaded_report
from nexus.tests.integration.operating_report_invoice_fixture import publish_selected_invoice
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_operating_report_denials import change_resource
from nexus.tests.integration.test_company_operating_reports import (
    reports_factory as reports_factory,
)
from nexus.tests.management_plan_support import VERIFIER


@pytest.mark.parametrize("private", [False, True])
async def test_actual_owner_billing_amount_keeps_independent_invoice_proof_permissions(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    private: bool,
) -> None:
    async def invoice_before_snapshot(policies: Policies, artifacts: BoundedArtifactReader) -> None:
        await publish_selected_invoice(reports_factory, tmp_path, policies, artifacts)
        if private:
            await change_resource(reports_factory, UUID(int=401), VERIFIER, active=False)

    scenario = await configured_report(
        reports_factory,
        tmp_path,
        issue_selected=True,
        selected_bill=None,
        release_selected=True,
        after_selected=invoice_before_snapshot,
    )
    assert scenario.saved.projection.actual_total_usd == Decimal("0.019000")
    assert UUID(int=401) in scenario.saved.data.required_resource_ids
    assert scenario.saved.projection.accepted_task_ids == ()
    if private:
        with pytest.raises(ValueError):
            await loaded_report(scenario)
    else:
        command = await loaded_report(scenario)
        assert (
            command.snapshot is not None and command.snapshot.operating == scenario.saved.projection
        )


async def test_unmapped_legacy_invoice_proof_is_native_owner_bill_without_source_read_grant(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async def legacy_invoice(policies: Policies, artifacts: BoundedArtifactReader) -> None:
        # M1 source adapter's legacy artifact namespace is deliberately absent from the Brain index.
        await publish_selected_invoice(
            reports_factory,
            tmp_path,
            policies,
            artifacts,
            proof_artifact_id=uuid4(),
        )

    with pytest.raises(ValueError):
        await configured_report(
            reports_factory,
            tmp_path,
            issue_selected=True,
            selected_bill=None,
            release_selected=True,
            after_selected=legacy_invoice,
        )
    async with brain_transaction(reports_factory, owner_scope(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert await session.scalar(select(func.count()).select_from(BillingEvidence)) == 1
        assert await session.scalar(select(CostHold.actual_usd)) == Decimal("0.019000")
        assert await session.scalar(select(func.count()).select_from(ManagementReportSnapshot)) == 0


async def test_author_inputs_return_actual_invoice_and_baseline_refs_with_same_snapshot(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    from uuid import uuid4

    from nexus.company.brain.base import BrainReadScope

    async def invoice_before_snapshot(policies: Policies, artifacts: BoundedArtifactReader) -> None:
        await publish_selected_invoice(reports_factory, tmp_path, policies, artifacts)

    scenario = await configured_report(
        reports_factory,
        tmp_path,
        issue_selected=True,
        selected_bill=None,
        release_selected=True,
        after_selected=invoice_before_snapshot,
    )
    author = scenario.saved.selection.author
    actual = BrainReadScope(
        company_id=author.company_id,
        workspace_id=author.workspace_id,
        principal_id=author.actor_id,
        operation_id=uuid4(),
        trace_id=uuid4(),
        task_id=author.task_id,
        task_trace_id=author.trace_id,
        actor_id=author.actor_id,
    )
    async with brain_transaction(reports_factory, actual, identity(author.actor_id)) as (
        session,
        current,
        _,
    ):
        record, inputs = await scenario.store.prepare_author_inputs(
            session, current, actual, identity(author.actor_id), scenario.saved.report_id
        )
    assert record == scenario.saved
    assert UUID(int=403) in {row.artifact_revision_id for row in inputs}
    assert (
        scenario.target.artifacts[0] not in inputs
    )  # Output author/verifier are excluded from selected costs/inputs.
    assert len({row.artifact_revision_id for row in inputs}) == len(inputs)
