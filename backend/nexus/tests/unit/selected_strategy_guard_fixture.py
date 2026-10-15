"""Typed guard delivery fixture; no native SQL, artifact READ or complete proof is qualified."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.selected_strategy_guard import StrategySelectedBuilderGuard
from nexus.builder.selected_strategy_services import SelectedBuilderEntry, SelectedBuilderServices
from nexus.builder.source_guard import BuilderSourceGuard, RegisteredBuilderSource
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.notifications.worker_identity import _verify
from nexus.company.strategy.actor_proof_contracts import SelectedStrategyProof
from nexus.company.strategy.actor_proof_reader import StrategyActorProofReader
from nexus.company.strategy.artifact_contracts import StrategyArtifactRule
from nexus.company.strategy.input_reader import StrategyInputReader
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl
from nexus.tests.unit.selected_strategy_pins_fixture import selected_case
from nexus.tests.unit.strategy_publication_reader_fixture import Policies
from nexus.tests.unit.strategy_stage_partition_fixture import execution
from nexus.tests.unit.strategy_transition_observation_fixture import transition_case


@dataclass
class GuardCase:
    guard: StrategySelectedBuilderGuard
    services: SelectedBuilderServices
    original: BuilderSourceGuard
    selected: SelectedStrategyProof
    session: MagicMock
    control: CompanyControl
    work: ExecutionWork
    now: datetime
    order: list[str]


def guard_case(monkeypatch: pytest.MonkeyPatch) -> GuardCase:
    # Keep this >50-line explicitly mocked delivery fixture's linked typed descriptions together.
    from nexus.builder import selected_strategy_guard as module

    cycle, pins = transition_case(2), selected_case()
    catalog, now = cycle.catalog, cycle.now
    admission = catalog.cycle_admission
    assert admission is not None
    bound = admission.slots[2].child.binding
    credential = _verify(
        SecretStr(
            jwt.encode(
                {
                    "sub": str(bound.actor_id),
                    "workspace_id": str(bound.workspace_id),
                    "iat": int(now.timestamp()) - 1,
                    "exp": int(now.timestamp()) + 300,
                },
                "public-selected-guard-synthetic-key-not-a-live-secret-at-least64",
                algorithm="HS256",
            )
        ),
        SecretStr("public-selected-guard-synthetic-key-not-a-live-secret-at-least64"),
    )
    candidate = pins.candidate.model_copy(update={"tool": admission.slots[2].tool})
    assert candidate.tool is not None
    policy = cycle.proof.original.prepared.original.snapshot.policy.model_copy(
        update={"candidates": (candidate, pins.candidate_policy.candidates[1])}
    )
    builder_policy = pins.policy.model_copy(update={"resource_symbol": candidate.tool.resource})
    template = pins.template.model_copy(
        update={
            "goal_id": policy.goal_id,
            "candidate_policy_sha256": canonical_sha256(policy),
            "candidate_scope_sha256": canonical_sha256(candidate),
            "repository": policy.repository,
            "tool": candidate.tool,
            "policy": builder_policy,
            "output_resource": catalog.resources[0].resource,
        }
    )
    spec = pins.spec.model_copy(
        update={
            "policy_sha256": canonical_sha256(builder_policy),
            "output_resource": template.output_resource,
            "job": pins.spec.job.model_copy(
                update={
                    "company_id": bound.company_id,
                    "task_id": bound.task_id,
                    "trace_id": bound.trace_id,
                    "run_id": bound.run_id,
                    "actor_id": bound.actor_id,
                    "workspace_id": bound.workspace_id,
                    "resource_symbol": builder_policy.resource_symbol,
                    "source": policy.repository,
                }
            ),
        }
    )
    original_bundle = cycle.proof.original.prepared.original
    prepared = cycle.proof.original.prepared.model_copy(
        update={
            "original": original_bundle.model_copy(
                update={"snapshot": original_bundle.snapshot.model_copy(update={"policy": policy})}
            )
        }
    )
    publication = cycle.proof.original.model_copy(update={"prepared": prepared})
    initial = replace(
        cycle.proof.initial, sources=replace(cycle.proof.initial.sources, credential=credential)
    )
    current = replace(
        cycle.proof.current, sources=replace(cycle.proof.current.sources, credential=credential)
    )
    proof = replace(cycle.proof, original=publication, initial=initial, current=current)
    binding = CurrentPlanBinding(
        company_id=bound.company_id,
        plan=proof.original.prepared.original.snapshot.scope.producing_plan.model_copy(
            update={"revision": 2}
        ),
        child=admission.slots[2].child,
        work=admission.slots[2].work,
        work_sha256="f" * 64,
        procedure_id=admission.procedure.procedure_id,
    )
    selected = SelectedStrategyProof(binding, proof, candidate, now)
    artifacts = MagicMock(spec=BoundedArtifactReader)
    artifacts.factory, artifacts.blobs = MagicMock(), MagicMock()
    base = SourcePolicy(
        source_symbol="generated.strategy-inputs.v2",
        authority_profile="fixture",
        data_classification="internal",
        origin_kind="derived",
        media_type="application/json",
        parser_version="json-v1",
        chunker_version="utf8-v1",
        search_config="simple",
        freshness_seconds=None,
    )
    policies = Policies(
        (
            base,
            base.model_copy(update={"source_symbol": "generated.strategy.v1", "max_bytes": 262144}),
            base.model_copy(
                update={"source_symbol": "generated.strategy-check.v1", "max_bytes": 262144}
            ),
        )
    )
    rules = tuple(
        StrategyArtifactRule.model_validate(
            {
                "company_id": bound.company_id,
                "tool": slot.tool.tool,
                "resource_symbol": slot.tool.resource,
                "target": catalog.resources[0].resource,
                "source_policy": symbol,
            }
        )
        for slot, symbol in zip(
            admission.slots[:2],
            ("generated.strategy.v1", "generated.strategy-check.v1"),
            strict=True,
        )
    )
    reader = StrategyActorProofReader(
        StrategyInputReader(
            artifacts,
            policies,
            catalog,
            original_bundle.policy,
            blobs=artifacts.blobs,
            write_rule=rules[0],
            check_rule=rules[1],
        )
    )
    lease = ExecutionLease(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        workspace_id=bound.workspace_id,
        run_id=bound.run_id,
        workflow_version="v1",
        segment_id=UUID(int=900),
        worker_id=UUID(int=901),
        fence=1,
        expires_at=now + timedelta(seconds=120),
        mode="execute",
    )
    original = BuilderSourceGuard(
        spec,
        builder_policy,
        lease,
        credential.identity,
        RegisteredBuilderSource(Path("/descriptive/repository"), template.source_metadata),
        artifacts,
        reader.reader.freshness,
        catalog,
    )
    entries = tuple(
        SelectedBuilderEntry(slot.child.binding, template) for slot in admission.slots[2:4]
    )
    services = SelectedBuilderServices(reader, entries)
    guard = services.resolve_guard(original, credential)
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=now)
    work = execution(
        bound,
        admission.slots[2].work,
        admission.slots[2].child.quota,
        admission.procedure.binding.task_id,
        1,
    )
    order: list[str] = []

    async def base_windows(*args: object) -> tuple[datetime, ...]:
        order.append("base")
        return (now + timedelta(seconds=90),)

    async def delivery(*args: object, **kwargs: object) -> SelectedStrategyProof:
        order.append("actor")
        assert args[0] is session and args[2] is work
        assert kwargs["credential"] is credential
        return selected

    monkeypatch.setattr(BuilderSourceGuard, "disclosure_windows", base_windows)
    monkeypatch.setattr(reader, "load_selected_locked", delivery)
    monkeypatch.setattr(module, "execution_row", AsyncMock(return_value=work))
    monkeypatch.setattr(module, "db_now", AsyncMock(return_value=now))
    control = CompanyControl(
        company_id=bound.company_id, owner_id=admission.procedure.binding.actor_id, paused=False
    )
    return GuardCase(guard, services, original, selected, session, control, work, now, order)
