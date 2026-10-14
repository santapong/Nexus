"""Actual distinct native plan verifier uses one new approved action and current lease."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.contracts.actions import ActionProposal
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.tests.builder_runtime_support import BuilderScenario
from nexus.tests.integration.management_acceptance_fixture import ledger
from nexus.tests.integration.test_company_directory import OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_plan_support import VERIFIER


async def verifier(item: BuilderScenario) -> BuilderScenario:
    binding = item.verifier_binding
    original = item.spec.job
    job = type(original).model_validate_json(
        original.model_copy(
            update={
                "task_id": binding.task_id,
                "trace_id": binding.trace_id,
                "actor_id": binding.actor_id,
                "run_id": binding.run_id,
                "workspace_id": binding.workspace_id,
                "action_id": uuid4(),
            }
        ).model_dump_json()
    )
    spec = BuilderExecutionSpec(
        job=job,
        policy_sha256=item.spec.policy_sha256,
        protected_patch=item.spec.protected_patch,
        output_resource=item.spec.output_resource,
    )
    action = ActionProposal(
        company_id=job.company_id,
        action_id=job.action_id,
        task_id=job.task_id,
        trace_id=job.trace_id,
        actor_id=VERIFIER,
        revision=1,
        tool="company.builder.run.v1",
        tool_version="v1",
        resource=job.resource_symbol,
        parameters=spec.model_dump(mode="json"),
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal("0.01"),
    )
    journal = CompanyJournal(item.runner.factory)
    await journal.submit(action, ledger(binding))
    await journal.approve_registered(
        ledger(binding).model_copy(update={"principal_id": OWNER}),
        action.action_id,
        action_hash(action),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        ledger(binding), action.action_id, datetime.now(UTC), (), identity=identity(VERIFIER)
    )
    lease = await item.runner.execution.claim(
        ledger(binding), identity(VERIFIER), uuid4(), ttl_seconds=60
    )
    old = item.guard
    guard = BuilderSourceGuard(
        spec,
        item.runner.policy,
        lease,
        identity(VERIFIER),
        old.source,
        old.artifacts,
        old.freshness,
        old.catalog,
    )
    return BuilderScenario(item.runner, spec, action, lease, guard, binding)
