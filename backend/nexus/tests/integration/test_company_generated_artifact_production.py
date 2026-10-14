"""Real production renderer/validator publishes report and independent mechanical result bytes."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.acceptance_models import ManagementWorkAcceptance
from nexus.company.management.check_contracts import ReportCheckResult
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactActionParameters
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.tests.generated_artifact_fixture import generated_scenario, ledger
from nexus.tests.generated_artifact_support import generated_factory as generated_factory
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity


async def test_real_producer_validator_publishes_report_and_check_without_forging_acceptance(
    generated_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    # Complete report→actual receipt→distinct verifier→recomputed check remains in
    # one >50-line scenario, with no supplied verdict or raw operative SQL setup.
    scenario = await generated_scenario(generated_factory, tmp_path, production=True)
    output = await scenario.publisher.publish(
        scenario.lease,
        identity(scenario.lease.actor_id),
        scenario.action.action_id,
        scenario.prepared,
    )
    receipt = ActionReceipt(
        company_id=COMPANY,
        receipt_id=uuid4(),
        action_id=scenario.action.action_id,
        task_id=scenario.lease.task_id,
        trace_id=scenario.lease.trace_id,
        proposal_hash=action_hash(scenario.action),
        outcome="succeeded",
        recorded_at=datetime.now(UTC),
        artifacts=(
            ArtifactRef(
                company_id=COMPANY,
                artifact_id=output.artifact_id,
                reference="protected:native-report",
                sha256=output.sha256,
                revision=output.revision,
            ),
        ),
    )
    await scenario.effects.record_receipt(
        scenario.lease, identity(scenario.lease.actor_id), receipt, actual_usd=Decimal("0")
    )
    verifier = scenario.payload.children[1].binding
    lease = await scenario.execution.claim(ledger(verifier), identity(verifier.actor_id), uuid4())
    prepared = await scenario.producer.prepare_check(
        lease, identity(verifier.actor_id), scenario.action.action_id
    )
    result = ReportCheckResult.model_validate_json(prepared.raw_bytes)
    assert result.verdict == "pass"
    parameters = GeneratedArtifactActionParameters(
        recipe_version=prepared.recipe_version,
        output_sha256=prepared.output_sha256,
        input_snapshot_sha256=prepared.input_snapshot_sha256,
        verification_target_sha256=result.target_sha256,
        author_action_id=scenario.action.action_id,
    )
    action = ActionProposal(
        company_id=COMPANY,
        action_id=uuid4(),
        task_id=verifier.task_id,
        trace_id=verifier.trace_id,
        actor_id=verifier.actor_id,
        revision=1,
        tool=scenario.rules[1].tool,
        tool_version="v1",
        resource=scenario.rules[1].resource_symbol,
        parameters=parameters.model_dump(mode="json", exclude_none=True),
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal("0.03"),
    )
    journal = CompanyJournal(generated_factory)
    await journal.submit(action, ledger(verifier))
    await journal.approve_registered(
        ledger(verifier).model_copy(update={"principal_id": OWNER}),
        action.action_id,
        action_hash(action),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        ledger(verifier),
        action.action_id,
        datetime.now(UTC),
        (),
        identity=identity(verifier.actor_id),
    )
    await scenario.effects.begin(lease, identity(verifier.actor_id), action.action_id)
    protected = await scenario.publisher.publish(
        lease, identity(verifier.actor_id), action.action_id, prepared
    )
    assert (
        await scenario.blobs.read(protected) == prepared.raw_bytes
        and protected.artifact_revision_id != output.artifact_revision_id
    )
    assert (
        await scenario.publisher.publish(
            lease, identity(verifier.actor_id), action.action_id, prepared
        )
        == protected
    )
    async with generated_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(ManagementWorkAcceptance)) == 0
