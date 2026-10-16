"""Actual concrete constructors and signed test JWT; source/parent SQL IO supplied explicitly."""

from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import jwt
from pydantic import SecretStr

from nexus.builder.contained_contracts import ScopeExpectation
from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
from nexus.builder.contained_evidence_types import ObservationDeadline
from nexus.builder.contained_intent_check import ContainedParentIntentCheck
from nexus.builder.contained_query import clock_us
from nexus.builder.contained_services import ContainmentServices
from nexus.builder.contracts import BuilderJobSpec, BuilderLimits, CommandRef, RepositoryPin
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256
from nexus.builder.nexus_source_guard import NexusBuilderSourceGuard
from nexus.builder.policy import BuilderCommandPolicy, BuilderToolPolicy
from nexus.builder.runtime_identity import RUNTIME_V2, RUNTIME_V2_METHOD_SHA256
from nexus.builder.source_guard import BuilderSourceGuard, RegisteredBuilderSource
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
from nexus.execution.effect_store import EffectStore
from nexus.execution.intent_checks import CompositeBeforeIntentCheck
from nexus.harness.canonical import action_hash
from nexus.tests.unit.nexus_cycle_fixture import key
from nexus.tests.unit.nexus_intent_fixture import Boundary


async def builder_check(
    value: Boundary, store: EffectStore, tmp_path: Path
) -> CompositeBeforeIntentCheck:
    job = BuilderJobSpec(
        company_id=value.work.company_id,
        task_id=value.work.task_id,
        trace_id=value.work.trace_id,
        run_id=value.work.run_id,
        workspace_id=value.work.workspace_id,
        actor_id=value.work.actor_id,
        action_id=value.action.id,
        policy_symbol="nexus.component.v1",
        resource_symbol="nexus.builder",
        architecture="amd64",
        source=RepositoryPin(
            repository_symbol="nexus", commit="1" * 40, tree="2" * 40, archive_sha256="3" * 64
        ),
        write_paths=("nexus",),
        artifact_paths=("checks",),
        commands=(
            CommandRef(command_key="unit", phase="baseline"),
            CommandRef(command_key="unit", phase="post"),
        ),
        limits=BuilderLimits(),
    )
    policy = BuilderToolPolicy(
        company_id=job.company_id,
        policy_symbol=job.policy_symbol,
        resource_symbol=job.resource_symbol,
        repository_symbol="nexus",
        image="registry.example/nexus@sha256:" + "a" * 64,
        commands=(
            BuilderCommandPolicy(
                command_key="unit", argv=("python", "-m", "pytest"), directory="."
            ),
        ),
        write_paths=job.write_paths,
        artifact_paths=job.artifact_paths,
        runtime_recipe=RUNTIME_V2,
        runtime_method_sha256=RUNTIME_V2_METHOD_SHA256,
        full_execution_method_sha256=CONTAINED_EXECUTION_METHOD_SHA256,
    )
    spec = BuilderExecutionSpec(
        job=job, policy_sha256=canonical_sha256(policy), runtime_recipe=RUNTIME_V2
    )
    unit = "nexus-component.scope"
    expected = ScopeExpectation(
        task_id=job.task_id,
        trace_id=job.trace_id,
        company_id=job.company_id,
        action_id=job.action_id,
        run_id=job.run_id,
        uid=1000,
        boot_id=key("boot"),
        unit=unit,
        invocation_id=key("invocation"),
        launcher_nonce=key("launcher"),
        mount_id=32,
        mount_device=27,
        mount_inode=1,
        cgroup_path="/fixture/" + unit,
        cgroup_inode=100,
        memory_bytes=4294967296,
        cpu_quota_us=200000,
        cpu_period_us=100000,
        pids=256,
        runtime_us=1200000000,
        stop_us=1000000,
        minimum_remaining_us=1000000,
    )
    containment = ContainmentServices(expected, ContainmentEvidenceStore(tmp_path / "contained"))
    containment.deadline = ObservationDeadline(end_us=clock_us() + 60_000_000)
    factory = store._factory
    artifacts = BoundedArtifactReader(factory, MagicMock())
    freshness = RegisteredSourceFreshness(factory, MagicMock())
    metadata = ArtifactRevisionRef(
        company_id=job.company_id,
        artifact_id=key("metadata"),
        artifact_revision_id=key("metadata-r1"),
        revision="r1",
        sha256="d" * 64,
        byte_length=100,
    )
    original = BuilderSourceGuard(
        spec,
        policy,
        value.lease,
        value.identity,
        RegisteredBuilderSource(tmp_path / "repository", metadata),
        artifacts,
        freshness,
        value.catalog,
        containment=containment,
    )
    key_value = SecretStr("nexus-component-public-test-key-at-least32bytes")
    token = SecretStr(
        jwt.encode(
            {
                "sub": str(value.identity.principal_id),
                "workspace_id": str(value.identity.workspace_id),
                "iat": int((value.now - timedelta(seconds=1)).timestamp()),
                "exp": int((value.lease.expires_at + timedelta(seconds=5)).timestamp()),
            },
            key_value.get_secret_value(),
            algorithm="HS256",
        )
    )

    class Credentials:
        async def credential(self) -> SecretStr:
            return token

    provider = NotificationWorkerIdentities(Credentials(), key_value, enabled=True)
    credential = await provider.current()
    guard = NexusBuilderSourceGuard(original, credential)
    action = ActionProposal.model_validate_json(value.action.proposal_json)
    action = action.model_copy(update={"parameters": spec.model_dump(mode="json")})
    value.action.proposal_json = action.model_dump_json()
    value.action.proposal_hash = action_hash(action)
    return CompositeBeforeIntentCheck((guard, ContainedParentIntentCheck(containment)))
