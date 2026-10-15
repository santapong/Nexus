"""Protected C-reader orchestration fixture; current pair/SQL are explicitly mocked."""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt
import pytest
from pydantic import SecretStr

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity, _verify
from nexus.company.strategy import result_reader as module
from nexus.company.strategy.artifact_contracts import StrategyArtifactRule, StrategyCheckParameters
from nexus.company.strategy.artifact_identity import strategy_derivation_id, strategy_reference
from nexus.company.strategy.check_output import prepare_strategy_check
from nexus.company.strategy.input_reader import StrategyInputReader
from nexus.company.strategy.publication_protection import StrategyCheckMaterial
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.harness.journal_models import JournalAction
from nexus.tests.unit.strategy_brief_fixture import strategy_case
from nexus.tests.unit.strategy_publication_flow_fixture import PublicationFlow, publication_flow


@dataclass
class ResultCase:
    flow: PublicationFlow
    reader: MagicMock
    lease: ExecutionLease
    credential: AuthenticatedWorkerIdentity
    material: StrategyCheckMaterial
    current: StrategyCheckMaterial
    row: BrainArtifactRevision
    record: JournalAction
    verifier_action_id: UUID
    graph: AsyncMock


def result_case(monkeypatch: pytest.MonkeyPatch) -> ResultCase:
    # This >50-line fixture keeps a genuine SV credential, exact C pins and old/current windows.
    flow = publication_flow(monkeypatch)
    original = flow.prepared.original.snapshot
    bound = original.scope.verifier
    now = flow.source.clock["now"]
    key = SecretStr("public-synthetic-strategy-result-key-at-least64-characters-for-tests-only")
    credential = _verify(
        SecretStr(
            jwt.encode(
                {
                    "sub": str(bound.actor_id),
                    "workspace_id": str(bound.workspace_id),
                    "iat": int(now.timestamp()) - 1,
                    "exp": int(now.timestamp()) + 300,
                },
                key.get_secret_value(),
                algorithm="HS256",
            )
        ),
        key,
    )
    lease = flow.lease.model_copy(
        update={
            "actor_id": bound.actor_id,
            "task_id": bound.task_id,
            "trace_id": bound.trace_id,
            "run_id": bound.run_id,
        }
    )
    command = strategy_case().command
    target = command.target.model_copy(
        update={"action_id": flow.prepared.action_id, "artifacts": (flow.prepared.brief,)}
    )
    command = command.model_copy(
        update={
            "target": target,
            "snapshot": original,
            "output": flow.prepared.brief,
            "output_utf8": flow.prepared.compiled.prepared.raw_bytes,
        }
    )
    inputs = GeneratedArtifactInputs(
        **original.inputs.model_dump(exclude={"artifacts", "required_resource_ids"}),
        artifacts=(
            *original.inputs.artifacts,
            flow.prepared.compiled.original_bundle.artifact,
            flow.prepared.brief,
        ),
        required_resource_ids=(
            *original.inputs.required_resource_ids,
            flow.prepared.compiled.original_bundle.resource.resource_id,
        ),
    )
    first_read = replace(
        flow.first.read, sources=replace(flow.first.read.sources, credential=credential)
    )
    next_read = replace(
        flow.second.read, sources=replace(flow.second.read.sources, credential=credential)
    )
    material = StrategyCheckMaterial(command, inputs, "internal", first_read)
    current = StrategyCheckMaterial(command, inputs, "internal", next_read)
    prepared = prepare_strategy_check(command, inputs, "internal")
    action_id = UUID(int=901)
    rule = StrategyArtifactRule(
        company_id=original.company_id,
        tool="company.cycle-artifact.check.v1",
        resource_symbol="strategy.check",
        target=ResourceRef(company_id=original.company_id, resource_id=UUID(int=510)),
        source_policy="generated.strategy-check.v1",
    )
    parameters = StrategyCheckParameters(
        author_action_id=flow.prepared.action_id,
        verification_target_sha256=canonical_sha256(target),
        output_sha256=prepared.output_sha256,
        input_snapshot_sha256=prepared.input_snapshot_sha256,
    )
    action = ActionProposal(
        company_id=original.company_id,
        action_id=action_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        revision=1,
        tool=rule.tool,
        tool_version="v1",
        resource=rule.resource_symbol,
        parameters=parameters.model_dump(mode="json"),
        policy_version="p1",
        price_version="p1",
        estimated_cost_usd=Decimal(".01"),
    )
    record = JournalAction(
        id=action_id,
        company_id=original.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        state="authorized",
        consumed_at=now,
        proposal_json=action.model_dump_json(),
    )
    from nexus.harness.canonical import action_hash

    record.proposal_hash = action_hash(action)
    reference = strategy_reference(prepared, action_id)
    row = BrainArtifactRevision(
        company_id=original.company_id,
        artifact_id=reference.artifact_id,
        artifact_revision_id=reference.artifact_revision_id,
        revision=reference.revision,
        sha256=reference.sha256,
        byte_length=reference.byte_length,
        raw_text=prepared.raw_bytes.decode(),
        resource_id=rule.target.resource_id,
        derivation_id=strategy_derivation_id(original.company_id, action_id),
        media_type="application/json",
        storage_symbol="fixture",
        data_classification="internal",
        recorded_at=now,
    )
    reader = MagicMock(spec=StrategyInputReader)
    reader.rules = MagicMock()
    reader.rules.check = rule
    reader.blobs = flow.store.blobs
    reader.artifacts = MagicMock()
    reader.artifacts.revalidate_artifact_reference = AsyncMock()
    reader.load_check_locked = AsyncMock(return_value=current)
    flow.session.get = AsyncMock(return_value=record)
    monkeypatch.setattr(module, "exact_artifact", AsyncMock(return_value=row))
    monkeypatch.setattr(module, "execution_row", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(module, "require_lease", MagicMock())

    async def clock(*_: object) -> datetime:
        return flow.source.clock["now"]

    monkeypatch.setattr(module, "db_now", clock)
    graph = AsyncMock()
    monkeypatch.setattr(module, "require_strategy_check_replay_locked", graph)
    return ResultCase(
        flow, reader, lease, credential, material, current, row, record, action_id, graph
    )
