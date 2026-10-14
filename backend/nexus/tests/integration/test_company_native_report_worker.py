"""Native step recovery uses actual issued check data, not a cached effect permission."""

from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.acceptance_evidence import ProtectedReportEvidenceResolver
from nexus.company.management.acceptance_recovery import AcceptanceRecovery
from nexus.company.management.acceptance_store import WorkAcceptanceStore
from nexus.company.management.scheduling_contracts import WorkflowRegistration
from nexus.execution.native_report_services import (
    NATIVE_APPLICATION,
    NATIVE_QUEUE,
    NATIVE_VERSION,
    NATIVE_WORKFLOW,
    NativeReportServices,
)
from nexus.execution.native_report_worker import execute_native_report
from nexus.tests.generated_artifact_fixture import GeneratedScenario, ledger
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_scheduler_support import FixtureIdentities, FixtureResources
from nexus.tests.native_workflow_support import (
    known_check,
    prepare_check_dispatch,
    published_author,
)
from nexus.tests.native_workflow_support import workflow_factory as workflow_factory


def worker_services(
    factory: async_sessionmaker[AsyncSession], scenario: GeneratedScenario
) -> NativeReportServices:
    """Actual production stores with explicit verified fixture actors, no live-provider evidence."""
    resolver = ProtectedReportEvidenceResolver(
        scenario.artifacts,
        scenario.producer.inputs,
        scenario.publisher.freshness,
    )
    return NativeReportServices(
        factory=factory,
        execution=scenario.execution,
        effects=scenario.effects,
        producer=scenario.producer,
        publisher=scenario.publisher,
        acceptance=WorkAcceptanceStore(factory, resolver),
        recovery=AcceptanceRecovery(factory, resolver, scenario.producer),
        artifacts=scenario.artifacts,
        identities=FixtureIdentities(),
        resources=FixtureResources(),
        registration=WorkflowRegistration(
            workflow_name=NATIVE_WORKFLOW,
            workflow_version=NATIVE_VERSION,
            queue_name=NATIVE_QUEUE,
            application_name=NATIVE_APPLICATION,
        ),
        worker_id=uuid4(),
        lease_ttl_seconds=60,
    )


async def test_native_step_recovers_actual_check_receipt_and_releases_capacity(
    workflow_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await known_check(workflow_factory, tmp_path)
    verifier = case.scenario.payload.children[1].binding
    before = await case.scenario.execution.release(case.original_lease, identity(verifier.actor_id))
    services = worker_services(workflow_factory, case.scenario)
    result = await execute_native_report(
        services, case.command, workflow_id=case.command.workflow_id
    )
    assert result.status == "accepted" and result.acceptance_id is not None
    after = await case.scenario.execution.get(ledger(verifier), identity(verifier.actor_id))
    assert after.worker_id is None and after.expires_at is None
    assert after.counters == before.counters and after.segment_number == before.segment_number
    replay = await execute_native_report(
        services, case.command, workflow_id=case.command.workflow_id
    )
    assert replay.acceptance_id == result.acceptance_id and replay.receipt_id == result.receipt_id


async def test_native_step_performs_one_fresh_check_and_publishes_independent_acceptance(
    workflow_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await published_author(workflow_factory, tmp_path)
    action, command = await prepare_check_dispatch(workflow_factory, scenario)
    verifier = scenario.payload.children[1].binding
    before = await scenario.execution.get(ledger(verifier), identity(verifier.actor_id))
    phases: list[str] = []
    from dataclasses import replace

    from nexus.execution.dbos_contracts import SegmentCommand
    from nexus.execution.native_report_services import NativePhase

    async def observe(phase: NativePhase, command: SegmentCommand) -> None:
        phases.append(phase)

    services = replace(worker_services(workflow_factory, scenario), hook=observe)
    result = await execute_native_report(services, command, workflow_id=command.workflow_id)
    assert result.status == "accepted", result
    assert phases == [
        "intent_committed",
        "artifact_published",
        "receipt_recorded",
        "acceptance_recorded",
    ]
    after = await scenario.execution.get(ledger(verifier), identity(verifier.actor_id))
    assert after.counters.tool_attempts == before.counters.tool_attempts + 1
    assert after.counters.model_requests == before.counters.model_requests == 0
    assert after.worker_id is None and result.action_id == action.action_id
