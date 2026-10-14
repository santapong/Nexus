"""Native preparation recomputes actual saved facts; supplied bytes never become authority."""

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import ReportCheckResult
from nexus.company.management.native_report_producer import NativeReportProducer
from nexus.settings import settings
from nexus.tests.integration.operating_report_fixture import configured_report
from nexus.tests.integration.test_company_directory import migrate
from nexus.tests.integration.test_company_execution_store import identity


@pytest.fixture
async def native_reports_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_native_reports"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
    )
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


async def test_native_preparation_and_revalidation_use_actual_saved_report(
    native_reports_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    scenario = await configured_report(native_reports_factory, tmp_path, source_no_ttl=True)
    author = scenario.saved.selection.author
    scope = BrainReadScope(
        company_id=author.company_id,
        workspace_id=author.workspace_id,
        principal_id=author.actor_id,
        operation_id=uuid4(),
        trace_id=uuid4(),
        task_id=author.task_id,
        task_trace_id=author.trace_id,
        actor_id=author.actor_id,
    )
    producer = NativeReportProducer(native_reports_factory, scenario.store, scenario.inputs)
    ids = tuple(
        claim.evidence_id for claim in scenario.report.claims if claim.kind == "source_quote"
    )
    payload = await producer.prepare_report(
        scope, identity(author.actor_id), scenario.saved.report_id, ids
    )
    assert payload.recipe_version == "native-report-render-v1"
    assert payload.inputs.contributors == tuple(
        head.current for head in scenario.saved.data.source_heads
    )
    assert set(scenario.saved.data.required_resource_ids) <= set(
        payload.inputs.required_resource_ids
    )
    async with brain_transaction(native_reports_factory, scope, identity(author.actor_id)) as (
        session,
        control,
        _,
    ):
        assert (
            await producer.recompute_report(
                session, control, scope, identity(author.actor_id), payload.raw_bytes
            )
            == payload
        )
        with pytest.raises(ValueError):
            await producer.recompute_report(
                session,
                control,
                scope,
                identity(author.actor_id),
                payload.raw_bytes.replace(b'"fresh"', b'"stale"'),
            )


async def test_actual_independent_check_preparation_preserves_native_target_and_result(
    native_reports_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    scenario = await configured_report(native_reports_factory, tmp_path, source_no_ttl=True)
    producer = NativeReportProducer(native_reports_factory, scenario.store, scenario.inputs)
    payload = await producer.prepare_check(
        scenario.verifier_lease,
        identity(scenario.target.verifier.actor_id),
        scenario.target.action_id,
    )
    result = ReportCheckResult.model_validate_json(payload.raw_bytes)
    assert result.verdict == "pass"
    assert result.target_sha256 == canonical_sha256(scenario.target)
    assert scenario.target.artifacts[0] in payload.inputs.artifacts
    assert set(scenario.saved.data.required_resource_ids) <= set(
        payload.inputs.required_resource_ids
    )
