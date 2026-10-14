"""Protected sharing and current native fingerprints fail closed under real restricted PG."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.acceptance_support import acceptance_scope
from nexus.company.management.operation_models import ManagementReportSnapshot
from nexus.company.management.report_rules import OperatingProjection
from nexus.tests.integration.operating_report_fixture import (
    ReportScenario,
    configured_report,
    loaded_report,
)
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_operating_reports import (
    reports_factory as reports_factory,
)


async def change_resource(
    factory: async_sessionmaker[AsyncSession],
    resource_id: UUID,
    principal: UUID,
    *,
    active: bool,
) -> None:
    async with brain_transaction(factory, owner_scope(), identity(OWNER)) as (session, _, _):
        resource = await session.get(BrainResource, (COMPANY, resource_id))
        assert resource is not None
        generation = resource.acl_generation
    await ResourceAccessStore(factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=resource_id),
            principal_id=principal,
            active=active,
            expected_generation=generation,
        ),
    )


async def shared_projection(
    factory: async_sessionmaker[AsyncSession],
    scenario: ReportScenario,
    *,
    mutate: str = "unchanged",
) -> OperatingProjection | None:

    verifier = scenario.payload.children[1].binding
    scope = acceptance_scope(scenario.verifier_lease, scenario.target.action_id)
    if mutate == "trace":
        scope = scope.model_copy(update={"task_trace_id": uuid4()})
    actual = identity(OWNER) if mutate == "principal" else identity(verifier.actor_id)
    report = scenario.report
    if mutate == "report":
        snapshot = report.operating.snapshot.model_copy(update={"report_id": uuid4()})
        report = report.model_copy(
            update={"operating": report.operating.model_copy(update={"snapshot": snapshot})}
        )
    output = scenario.target.artifacts[0]
    if mutate == "output":
        output = output.model_copy(update={"sha256": "f" * 64})
    async with brain_transaction(factory, scope, actual) as (session, current, _):
        result: OperatingProjection | None = await scenario.store.current_projection(
            session,
            current,
            scope,
            actual,
            report,
            output=output,
        )
        return result


@pytest.mark.parametrize("change", ["output", "trace", "principal", "report"])
async def test_declared_id_trace_principal_or_output_cannot_authorize_saved_facts(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    change: str,
) -> None:
    scenario = await configured_report(reports_factory, tmp_path)
    if change == "report":
        assert await shared_projection(reports_factory, scenario, mutate=change) is None
    else:
        with pytest.raises(ValueError):
            await shared_projection(reports_factory, scenario, mutate=change)


@pytest.mark.parametrize("principal", ["owner", "verifier"])
async def test_current_contributor_grant_required_even_for_saved_owner_projection(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    principal: str,
) -> None:
    scenario = await configured_report(reports_factory, tmp_path)
    actor = OWNER if principal == "owner" else scenario.payload.children[1].binding.actor_id
    await change_resource(reports_factory, RESOURCE, actor, active=False)
    with pytest.raises(ValueError):
        if principal == "owner":
            await scenario.store.get_saved(control(), identity(OWNER), scenario.saved.report_id)
        else:
            await loaded_report(scenario)


async def test_changed_native_work_is_inconclusive_not_reused_snapshot(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_report(reports_factory, tmp_path)
    await PersistentCompanyDirectory(reports_factory).set_work_active(
        control(),
        task_id=scenario.payload.children[2].binding.task_id,
        active=False,
    )
    assert await shared_projection(reports_factory, scenario) is None
    # Immutable historical owner evidence remains exactly dated.
    assert (
        await scenario.store.get_saved(control(), identity(OWNER), scenario.saved.report_id)
        == scenario.saved
    )


async def test_inactive_actual_member_cannot_read_shared_saved_report(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_report(reports_factory, tmp_path)
    await PersistentCompanyDirectory(reports_factory).set_membership(
        MembershipChange(
            company_id=COMPANY,
            principal_id=scenario.payload.children[1].binding.actor_id,
            role="member",
            membership_active=False,
        ),
        control(),
    )
    with pytest.raises(ValueError):
        await loaded_report(scenario)


async def test_report_envelope_is_append_only_and_company_scoped(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_report(reports_factory, tmp_path)
    with pytest.raises(DBAPIError):
        async with brain_transaction(reports_factory, owner_scope(), identity(OWNER)) as (
            session,
            _,
            _,
        ):
            await session.execute(update(ManagementReportSnapshot).values(snapshot_json="{}"))
    async with reports_factory() as session, session.begin():
        from sqlalchemy import func

        await session.execute(select(func.set_config("nexus.company_id", str(uuid4()), True)))
        assert (
            await session.get(ManagementReportSnapshot, (COMPANY, scenario.saved.report_id)) is None
        )


async def test_missing_selected_native_resource_map_cannot_borrow_output_scope(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_report(reports_factory, tmp_path)
    scenario.store.catalog = scenario.store.catalog.model_copy(update={"resources": ()})
    with pytest.raises(ValueError):
        await shared_projection(reports_factory, scenario)


async def test_unknown_selected_source_policy_denies_sharing_even_with_valid_output_policy(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
    from nexus.tests.integration.management_acceptance_source_fixture import Policies

    scenario = await configured_report(reports_factory, tmp_path)
    policies = Policies()
    # The protected output policy is qualified; the selected native input policy is absent.
    from nexus.company.brain.source_registry import SourcePolicy

    policies.values = {
        "acceptance.fixture.200": SourcePolicy(
            source_symbol="acceptance.fixture.200",
            authority_profile="fixture.reported.v1",
            data_classification="internal",
            media_type="text/plain",
            parser_version="utf8-identity-v1",
            chunker_version="utf8-sections-v1",
            search_config="simple",
            freshness_seconds=300,
            allowed_external_keys=frozenset({"source-200"}),
        )
    }
    scenario.store.freshness = RegisteredSourceFreshness(reports_factory, policies)
    with pytest.raises(ValueError):
        await shared_projection(reports_factory, scenario)


async def test_actual_source_revision_change_invalidates_current_projection_only(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    from nexus.company.brain.blob_store import ProtectedBlobStore
    from nexus.company.brain.ingestion_store import BrainIngestionStore
    from nexus.company.brain.source_registry import SourceRegistry
    from nexus.tests.integration.management_acceptance_source_fixture import Policies
    from nexus.tests.integration.test_company_brain_ingestion import SOURCE, Reader, command

    scenario = await configured_report(reports_factory, tmp_path)
    head = next(row for row in scenario.saved.data.source_heads if row.source_id == SOURCE)
    raw = b"New actual input revision changes the saved source snapshot."
    source = BrainIngestionStore(
        reports_factory,
        SourceRegistry((Policies().policy("fixture.source.v1"),), Reader({"2": raw})),
        ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1"),
    )
    await source.ingest(
        owner_scope(), identity(OWNER), command(raw, "2", head.current.source_revision_id)
    )
    assert await shared_projection(reports_factory, scenario) is None
    assert (
        await scenario.store.get_saved(control(), identity(OWNER), scenario.saved.report_id)
        == scenario.saved
    )


async def test_actual_m1_ledger_reconciliation_changes_current_report_fingerprint(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    from decimal import Decimal

    from nexus.harness.journal import CompanyJournal
    from nexus.tests.integration.management_acceptance_fixture import ledger

    scenario = await configured_report(
        reports_factory, tmp_path, issue_selected=True, selected_bill=None
    )
    assert scenario.selected_action_id is not None
    # Existing trusted M1 ledger path changes a real unknown charge, not the report or receipt.
    await CompanyJournal(reports_factory).reconcile(
        ledger(scenario.payload.children[2].binding),
        scenario.selected_action_id,
        Decimal("0.017000"),
    )
    assert await shared_projection(reports_factory, scenario) is None
    assert scenario.saved.projection.actual_total_usd is None


async def test_revoked_current_output_plan_cannot_share_saved_projection(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    from nexus.company.management.plan_store import ManagementPlanStore

    scenario = await configured_report(reports_factory, tmp_path)
    revision = scenario.saved.selection.plan
    await ManagementPlanStore(reports_factory, scenario.store.catalog).revoke(
        control(),
        identity(OWNER),
        revision.plan_revision_id,
        revision.sha256,
        expected_current_revision_id=revision.plan_revision_id,
    )
    with pytest.raises(ValueError):
        await loaded_report(scenario)
    assert (
        await scenario.store.get_saved(control(), identity(OWNER), scenario.saved.report_id)
        == scenario.saved
    )
