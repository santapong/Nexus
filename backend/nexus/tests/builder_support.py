"""Synthetic builder descriptions; positive capability DTO is never machine qualification."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from nexus.builder.contracts import (
    BuilderCapabilities,
    BuilderJobSpec,
    BuilderLimits,
    CommandRef,
    RepositoryPin,
)
from nexus.builder.policy import BuilderCommandPolicy, BuilderToolPolicy
from nexus.company.contracts.actions import ActionProposal
from nexus.execution.runtime_contracts import ExecutionLease

IMAGE = "registry.example/native@sha256:" + "1" * 64
COMPANY = UUID(int=8800)


def described_job() -> BuilderJobSpec:
    return BuilderJobSpec(
        company_id=COMPANY,
        task_id=uuid4(),
        trace_id=uuid4(),
        run_id=uuid4(),
        workspace_id=uuid4(),
        actor_id=uuid4(),
        action_id=uuid4(),
        policy_symbol="stockflow.check.v1",
        resource_symbol="stockflow.repository",
        architecture="arm64",
        source=RepositoryPin(
            repository_symbol="stockflow", commit="2" * 40, tree="3" * 40, archive_sha256="4" * 64
        ),
        write_paths=("apps/web/src",),
        artifact_paths=("checks",),
        commands=(
            CommandRef(command_key="unit", phase="baseline"),
            CommandRef(command_key="unit", phase="post"),
        ),
        limits=BuilderLimits(),
    )


def described_policy() -> BuilderToolPolicy:
    return BuilderToolPolicy(
        company_id=COMPANY,
        policy_symbol="stockflow.check.v1",
        resource_symbol="stockflow.repository",
        repository_symbol="stockflow",
        image=IMAGE,
        commands=(
            BuilderCommandPolicy(command_key="unit", argv=("pnpm", "test"), directory="apps/web"),
        ),
        write_paths=("apps/web/src",),
        artifact_paths=("checks",),
    )


def synthetic_capabilities() -> BuilderCapabilities:
    return BuilderCapabilities(
        architecture="arm64",
        rootless=True,
        cgroup_v2=True,
        controllers=frozenset({"cpu", "memory", "pids"}),
        hard_workspace_quota=True,
        network_none_verified=True,
        image_present=True,
        qualified_image=IMAGE,
    )


def described_binding(job: BuilderJobSpec) -> tuple[ActionProposal, ExecutionLease, datetime]:
    now = datetime.now(UTC)
    action = ActionProposal(
        company_id=job.company_id,
        action_id=job.action_id,
        task_id=job.task_id,
        trace_id=job.trace_id,
        actor_id=job.actor_id,
        revision=1,
        tool="company.builder.run.v1",
        tool_version="v1",
        resource=job.resource_symbol,
        parameters={"job": job.model_dump(mode="json")},
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal("0.01"),
    )
    lease = ExecutionLease(
        company_id=job.company_id,
        task_id=job.task_id,
        trace_id=job.trace_id,
        actor_id=job.actor_id,
        workspace_id=job.workspace_id,
        run_id=job.run_id,
        workflow_version="fixture-builder-v1",
        segment_id=uuid4(),
        worker_id=uuid4(),
        fence=1,
        expires_at=now + timedelta(seconds=10),
        mode="execute",
    )
    return action, lease, now
