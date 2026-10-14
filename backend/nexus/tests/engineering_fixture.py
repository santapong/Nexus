"""New explicit synthetic engineering procedure through actual public stores on own DB.

Fixture model-free admission is not StockFlow, model quality or private activation.
The long helper keeps complete real public setup/registration/approval visible.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.builder.contracts import (
    BuilderCapabilities,
    BuilderJobSpec,
    BuilderLimits,
    CommandRef,
)
from nexus.builder.engineering_acceptance import EngineeringWorkAcceptanceStore
from nexus.builder.engineering_artifacts import EngineeringArtifactPublisher
from nexus.builder.engineering_contracts import EngineeringChangeDeclaration
from nexus.builder.engineering_inputs import RegisteredEngineeringInputs
from nexus.builder.engineering_proof import EngineeringProofStorage
from nexus.builder.engineering_runner import EngineeringNativeBuilderRunner
from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.policy import BuilderCommandPolicy, BuilderToolPolicy
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.source_guard import BuilderSourceGuard, RegisteredBuilderSource
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.artifact_target_store import ArtifactTargetStore
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import NamedPlanResource, PlanAdmissionCatalog
from nexus.company.management.plans import PlanPayload, RunBinding
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.standing_contracts import ToolPermission
from nexus.settings import settings
from nexus.tests.builder_node_support import IMAGE, IMAGE_ID
from nexus.tests.engineering_fixture_source import CASES, generated_repository
from nexus.tests.integration.management_acceptance_source_fixture import Policies, protected_text
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control, migrate
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_control_support import charter
from nexus.tests.management_plan_support import VERIFIER
from nexus.tests.native_execution_profile_fixture import native_plan


@pytest.fixture
async def engineering_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_builder_engineering"
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


@dataclass(frozen=True)
class EngineeringScenario:
    acceptance: EngineeringWorkAcceptanceStore
    runner: EngineeringNativeBuilderRunner
    author: BuilderRunResult
    verifier: BuilderRunResult
    lease: ExecutionLease
    catalog: PlanAdmissionCatalog
    verifier_action: ActionProposal
    verifier_guard: BuilderSourceGuard


async def engineering_scenario(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    reserve_native_dispatch: bool = False,
    source_ttl: int | None = 300,
) -> EngineeringScenario:
    assert type(reserve_native_dispatch) is bool
    assert source_ttl is None or (type(source_ttl) is int and 1 <= source_ttl <= 300)
    plans, payload = await native_plan(factory, root)
    controls = ManagementControlStore(factory)
    charters = []
    for number, name in ((5101, "engineering"), (5102, "verification")):
        declared = charter("engineering-fixture-v1", verifier=VERIFIER).model_copy(
            update={
                "department_id": UUID(int=number),
                "name": name,
                "allowed_tools": ("company.builder.run.v1",),
                "resource_scopes": ("engineering.output",),
                "responsibilities": ("Synthetic quantity correctness fixture",),
                "deliverables": ("Actual bounded code/check evidence",),
            }
        )
        recorded = await controls.publish_charter(
            control(), identity(OWNER), declared, mandate=payload.mandate, expected_revision_id=None
        )
        charters.append(
            CharterRevisionRef.model_validate_json(
                recorded.model_dump_json(include=set(CharterRevisionRef.model_fields))
            )
        )
    output, proof_target = (ResourceRef(company_id=COMPANY, resource_id=uuid4()) for _ in range(2))
    for resource in (output, proof_target):
        await ArtifactTargetStore(factory).provision(
            owner_scope(), identity(OWNER), resource, readers=(OWNER, ACTOR, VERIFIER)
        )
    permission = ToolPermission(
        tool="company.builder.run.v1", tool_version="v1", resource="engineering.output"
    )
    catalog = plans.catalog.model_copy(
        update={
            "resources": (NamedPlanResource(symbol="engineering.output", resource=output),),
            "tools": (permission,),
            "native_profiles": tuple(
                item.model_copy(update={"tools": (permission,)})
                for item in plans.catalog.native_profiles
            ),
        }
    )
    payload = PlanPayload.model_validate_json(
        payload.model_copy(
            update={
                "charters": tuple(charters),
                "children": tuple(
                    child.model_copy(update={"charter": charters[index]})
                    for index, child in enumerate(payload.children)
                ),
                "plan": payload.plan.model_copy(
                    update={
                        "items": tuple(
                            item.model_copy(
                                update={
                                    "department": ("engineering", "verification")[index],
                                    "title": "Synthetic quantity change; no StockFlow claim",
                                }
                            )
                            for index, item in enumerate(payload.plan.items)
                        )
                    }
                ),
            }
        ).model_dump_json()
    )
    plans = ManagementPlanStore(factory, catalog)
    proposed = await plans.propose(
        control(), identity(OWNER), payload, expected_current_revision_id=None
    )
    await plans.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=proposed.plan_revision_id,
    )
    repository, pin, patch_raw = await asyncio.to_thread(generated_repository, root)
    blobs, policies = ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1"), Policies()
    metadata = await protected_text(
        factory,
        blobs,
        policies,
        json.dumps({"source": pin.model_dump(mode="json")}),
        9900,
        ttl=source_ttl,
    )
    patch = await protected_text(factory, blobs, policies, patch_raw.decode(), 9500, ttl=source_ttl)
    artifacts, freshness = (
        BoundedArtifactReader(factory, blobs),
        RegisteredSourceFreshness(factory, policies),
    )
    execution = ExecutionStore(
        factory,
        management_catalog=catalog,
        management_artifacts=artifacts,
        management_freshness=freshness,
    )
    effects = EffectStore(
        factory,
        management_catalog=catalog,
        management_artifacts=artifacts,
        management_freshness=freshness,
    )
    policy = BuilderToolPolicy(
        company_id=COMPANY,
        policy_symbol="fixture.engineering.v1",
        repository_symbol=pin.repository_symbol,
        resource_symbol="engineering.output",
        image=IMAGE,
        commands=(
            BuilderCommandPolicy(
                command_key="check", argv=("/usr/local/bin/node", "verify.cjs"), directory="."
            ),
        ),
        write_paths=("quantity.cjs",),
        artifact_paths=("checks",),
    )
    jobs = root / "jobs"
    jobs.mkdir(mode=0o700)
    publisher = EngineeringArtifactPublisher(
        factory, blobs, output, policies.policy("fixture.source.v1"), jobs
    )
    runner = EngineeringNativeBuilderRunner(
        factory,
        execution,
        effects,
        policy,
        BuilderCapabilities(
            architecture="amd64",
            rootless=True,
            cgroup_v2=True,
            controllers=frozenset({"cpu", "memory", "pids"}),
            hard_workspace_quota=True,
            network_none_verified=True,
            image_present=True,
            qualified_image=IMAGE,
        ),
        IMAGE_ID,
        BuilderResultStore(root / "results"),
        jobs,
        publisher,
    )
    results = []
    lease = None
    for child in payload.children:
        bound = child.binding
        job = BuilderJobSpec(
            company_id=COMPANY,
            task_id=bound.task_id,
            trace_id=bound.trace_id,
            run_id=bound.run_id,
            workspace_id=bound.workspace_id,
            actor_id=bound.actor_id,
            action_id=uuid4(),
            policy_symbol=policy.policy_symbol,
            resource_symbol=policy.resource_symbol,
            architecture="amd64",
            source=pin,
            patch_sha256=patch.sha256,
            write_paths=policy.write_paths,
            artifact_paths=policy.artifact_paths,
            commands=(
                CommandRef(command_key="check", phase="baseline"),
                CommandRef(command_key="check", phase="post"),
            ),
            limits=BuilderLimits(
                memory_bytes=67108864,
                workspace_bytes=4194304,
                output_bytes=1048576,
                log_bytes=16384,
                command_seconds=5,
                job_seconds=15,
                pids=32,
            ),
        )
        spec = BuilderExecutionSpec(
            job=job,
            policy_sha256=canonical_sha256(policy),
            protected_patch=patch,
            output_resource=output,
        )
        action = ActionProposal(
            company_id=COMPANY,
            action_id=job.action_id,
            task_id=job.task_id,
            trace_id=job.trace_id,
            actor_id=job.actor_id,
            revision=1,
            tool=permission.tool,
            tool_version=permission.tool_version,
            resource=permission.resource,
            parameters=spec.model_dump(mode="json"),
            policy_version="fixture-policy",
            price_version="fixture-prices",
            estimated_cost_usd=Decimal("0.01"),
        )
        scope = LedgerScope(
            company_id=COMPANY,
            task_id=bound.task_id,
            trace_id=bound.trace_id,
            principal_id=bound.actor_id,
        )
        journal = CompanyJournal(factory)
        await journal.submit(action, scope)
        await journal.approve_registered(
            scope.model_copy(update={"principal_id": OWNER}),
            action.action_id,
            action_hash(action),
            datetime.now(UTC),
            identity=identity(OWNER),
        )
        await journal.authorize_registered(
            scope, action.action_id, datetime.now(UTC), (), identity=identity(bound.actor_id)
        )
        segment_id = None
        if reserve_native_dispatch:
            segment_id = await reserve_engineering_dispatch(
                factory, execution, scope, bound, action
            )
        lease = await execution.claim(
            scope, identity(bound.actor_id), uuid4(), ttl_seconds=60, segment_id=segment_id
        )
        guard = BuilderSourceGuard(
            spec,
            policy,
            lease,
            identity(bound.actor_id),
            RegisteredBuilderSource(repository, metadata),
            artifacts,
            freshness,
            catalog,
        )
        result = await runner.run(lease, identity(bound.actor_id), action, spec, guard)
        assert result is not None and result.outcome == "commands_succeeded"
        assert publisher.witnesses == {}
        results.append(result)
    assert lease is not None
    declaration = EngineeringChangeDeclaration(
        company_id=COMPANY,
        goal_id=payload.goal.goal_id,
        procedure_id=payload.procedure.procedure_id,
        policy=policy,
        image_id=IMAGE_ID,
        behavior_case_ids=CASES,
    )
    inputs = RegisteredEngineeringInputs(
        factory, artifacts, runner.results, (declaration,), freshness
    )
    proof = EngineeringProofStorage(blobs, proof_target, policies.policy("fixture.source.v1"))
    return EngineeringScenario(
        EngineeringWorkAcceptanceStore(factory, catalog, inputs, proof),
        runner,
        results[0],
        results[1],
        lease,
        catalog,
        action,
        guard,
    )


async def reserve_engineering_dispatch(
    factory: async_sessionmaker[AsyncSession],
    execution: ExecutionStore,
    scope: LedgerScope,
    bound: RunBinding,
    action: ActionProposal,
) -> UUID:
    """Fixture invokes the real permanent native dispatch helper before an actual claim."""
    from nexus.execution.dbos_contracts import SegmentCommand
    from nexus.execution.dispatch_models import SegmentDispatch
    from nexus.execution.dispatch_store import reserve_dispatch
    from nexus.execution.runtime_store import next_segment_id
    from nexus.execution.runtime_support import runtime_transaction

    current = await execution.get(scope, identity(bound.actor_id))
    command = SegmentCommand(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        workspace_id=bound.workspace_id,
        run_id=bound.run_id,
        action_id=action.action_id,
        segment_id=next_segment_id(current),
    )
    async with runtime_transaction(factory, scope, identity(bound.actor_id)) as (session, _, _):
        await reserve_dispatch(
            session,
            command,
            workflow_name=bound.workflow_name,
            workflow_version=bound.workflow_version,
        )
        stored = await session.get(SegmentDispatch, (bound.company_id, action.action_id))
        assert stored is not None and stored.binding_json == command.model_dump_json()
        assert stored.workflow_id == command.workflow_id
    return command.segment_id
