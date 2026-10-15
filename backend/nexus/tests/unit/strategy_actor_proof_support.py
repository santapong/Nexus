"""Supplied typed Strategy material and mocked SQL boundaries; no real native/DB evidence."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import BrainBlobStore
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.management.plans import PlanPayload
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity, _verify
from nexus.company.strategy import actor_proof_reader as module
from nexus.company.strategy.actor_proof_contracts import SelectedStrategyProof
from nexus.company.strategy.actor_proof_reader import StrategyActorProofReader
from nexus.company.strategy.artifact_contracts import StrategyArtifactRule
from nexus.company.strategy.contracts import StrategyCandidateScope, StrategyCheckInput
from nexus.company.strategy.current_proof_read import StrategyProofMaterial
from nexus.company.strategy.input_reader import StrategyInputReader
from nexus.company.strategy.publication_protection import (
    StrategyCheckMaterial,
    StrategyProtectedPublication,
)
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl
from nexus.tests.unit.cycle_admission_fixture import declared
from nexus.tests.unit.strategy_publication_reader_fixture import Policies
from nexus.tests.unit.strategy_transition_observation_data import _work
from nexus.tests.unit.strategy_transition_observation_fixture import transition_case


@dataclass
class ActorCase:
    service: StrategyActorProofReader
    work: ExecutionWork
    control: CompanyControl
    credential: AuthenticatedWorkerIdentity
    binding: CurrentPlanBinding
    payload: PlanPayload
    record: ManagementPlanRevision
    candidate: StrategyCandidateScope
    materials: list[StrategyProofMaterial]
    session: MagicMock
    read_gate: AsyncMock
    partitions: AsyncMock
    binding_read: AsyncMock
    body_calls: list[BrainReadScope]
    clock: dict[str, datetime]
    material_failure: int | None = None
    after_second: Callable[[], None] | None = None

    def witness(self, who: str = "actor") -> AuthenticatedWorkerIdentity:
        admission = self.service.reader.catalog.cycle_admission
        assert admission is not None
        actor = {
            "actor": self.work.actor_id,
            "owner": self.control.owner_id,
            "author": admission.slots[0].child.binding.actor_id,
            "verifier": admission.slots[1].child.binding.actor_id,
            "foreign": UUID(int=999),
        }[who]
        key = SecretStr("synthetic-actor-proof-test-key-at-least64characters-not-a-live-secret")
        now = self.clock["now"]
        token = SecretStr(
            jwt.encode(
                {
                    "sub": str(actor),
                    "workspace_id": str(self.work.workspace_id),
                    "iat": int(now.timestamp()) - 1,
                    "exp": int(now.timestamp()) + 300,
                },
                key.get_secret_value(),
                algorithm="HS256",
            )
        )
        return _verify(token, key)

    async def read(self) -> SelectedStrategyProof:
        return await self.service.load_selected_locked(
            self.session,
            self.control,
            self.work,
            self.credential.identity,
            credential=self.credential,
        )

    def break_entry(self, which: str) -> None:
        if which == "transaction":
            self.session.in_transaction.return_value = False
        elif which == "pause":
            self.control.paused = True
        elif which == "company":
            self.work.company_id = UUID(int=999)
        elif which in {"blocked", "outcome_unknown"}:
            self.work.state = which
        elif which in {"run", "trace"}:
            setattr(self.work, f"{which}_id", UUID(int=999))
        elif which == "missing_binding":
            self.binding_read.return_value = None
        elif which == "missing_plan":
            self.session.get.return_value = None
        else:
            configured = self.service.reader.catalog.cycle_admission
            assert configured is not None
            changed = (
                declared(configured, 1)
                if which == "stage_one"
                else self.payload.model_copy(update={"strategy_selection": None})
            )
            self.record.snapshot_json = changed.model_dump_json()
            self.record.sha256 = canonical_sha256(changed)
            self.record.revision = changed.plan.revision

    def break_final(self, which: str) -> None:
        if which == "fence":
            self.work.fence += 1
        elif which == "binding":
            self.binding_read.return_value = self.binding.model_copy(
                update={"work_sha256": "f" * 64}
            )
        elif which == "head":
            self.binding_read.return_value = self.binding.model_copy(
                update={
                    "plan": self.binding.plan.model_copy(update={"plan_revision_id": UUID(int=999)})
                }
            )
        elif which == "blocked":
            self.work.state = "blocked"
        else:
            self.read_gate.side_effect = AcceptanceDeniedError("nominated final task READ denial")


def actor_case(monkeypatch: pytest.MonkeyPatch, *, verifier: bool = False) -> ActorCase:
    """Genuine constructors/JWT + pure native checks; SQL/material delivery is explicitly mocked."""
    data = transition_case(2)
    payload, supplied = data.payload, data.proof
    catalog = data.catalog
    admission = catalog.cycle_admission
    assert admission is not None
    index = 3 if verifier else 2
    work = _work(admission, index)
    work.state, work.fence, work.tool_attempts_used = "running", 7, 0
    control = CompanyControl(
        company_id=work.company_id, owner_id=admission.procedure.binding.actor_id, paused=False
    )
    reference = PlanRevisionRef(
        company_id=work.company_id,
        plan_id=payload.plan.plan_id,
        plan_revision_id=UUID(int=2000),
        revision=2,
        sha256=canonical_sha256(payload),
    )
    slot = admission.slots[index]
    binding = CurrentPlanBinding(
        company_id=work.company_id,
        plan=reference,
        child=slot.child,
        work=slot.work,
        work_sha256=work.registration_hash,
        procedure_id=payload.procedure.procedure_id,
    )
    record = ManagementPlanRevision(
        company_id=work.company_id,
        plan_id=reference.plan_id,
        plan_revision_id=reference.plan_revision_id,
        revision=2,
        goal_id=payload.goal.goal_id,
        goal_revision_id=payload.goal.revision_id,
        mandate_revision_id=payload.mandate.revision_id,
        snapshot_json=payload.model_dump_json(),
        sha256=reference.sha256,
        proposed_by=control.owner_id,
        recorded_at=data.now,
    )
    base_policy = SourcePolicy(
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
            base_policy,
            base_policy.model_copy(
                update={"source_symbol": "generated.strategy.v1", "max_bytes": 262144}
            ),
            base_policy.model_copy(
                update={"source_symbol": "generated.strategy-check.v1", "max_bytes": 262144}
            ),
        )
    )
    blobs = cast(BrainBlobStore, MagicMock())
    factory = cast(async_sessionmaker[AsyncSession], MagicMock())
    artifacts = BoundedArtifactReader(factory, blobs)
    target = catalog.resources[0].resource
    write = StrategyArtifactRule(
        company_id=work.company_id,
        tool="company.cycle-artifact.write.v1",
        resource_symbol=admission.slots[0].tool.resource,
        target=target,
        source_policy="generated.strategy.v1",
    )
    check = StrategyArtifactRule(
        company_id=work.company_id,
        tool="company.cycle-artifact.check.v1",
        resource_symbol=admission.slots[1].tool.resource,
        target=target,
        source_policy="generated.strategy-check.v1",
    )
    reader = StrategyInputReader(
        artifacts,
        policies,
        catalog,
        supplied.original.prepared.original.policy,
        blobs=blobs,
        write_rule=write,
        check_rule=check,
    )
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    session.get = AsyncMock(return_value=record)
    session.add, session.flush, session.commit = MagicMock(), AsyncMock(), AsyncMock()
    read_gate, partitions = AsyncMock(), AsyncMock()
    binding_read = AsyncMock(return_value=binding)
    case = ActorCase(
        StrategyActorProofReader(reader),
        work,
        control,
        supplied.current.sources.credential,
        binding,
        payload,
        record,
        data.observation.candidate,
        [],
        session,
        read_gate,
        partitions,
        binding_read,
        [],
        {"now": data.now},
    )
    case.credential = case.witness()
    read = replace(
        supplied.current, sources=replace(supplied.current.sources, credential=case.credential)
    )
    original = supplied.original.prepared.original.snapshot
    refs = (
        *original.inputs.artifacts,
        supplied.original.prepared.compiled.original_bundle.artifact,
        supplied.original.prepared.brief,
    )
    inputs = GeneratedArtifactInputs(
        **original.inputs.model_dump(exclude={"artifacts", "required_resource_ids"}),
        artifacts=tuple(sorted(refs, key=lambda row: row.artifact_revision_id)),
        required_resource_ids=tuple(
            sorted(
                set(original.inputs.required_resource_ids)
                | {supplied.original.prepared.compiled.original_bundle.resource.resource_id}
            )
        ),
    )
    command = StrategyCheckInput(
        company_id=work.company_id,
        target=supplied.acceptance.target,
        output=supplied.original.prepared.brief,
        output_utf8=supplied.original.prepared.compiled.prepared.raw_bytes,
        snapshot=original,
    )
    material = StrategyProofMaterial(
        supplied.acceptance,
        StrategyCheckMaterial(command, inputs, "internal", read),
        StrategyProtectedPublication(supplied.original, read),
        supplied.verifier,
        supplied.check_result.model_dump_json().encode(),
        data.now,
        2,
        2,
    )
    case.materials = [material, material]

    async def body(*args: object, **kwargs: object) -> StrategyProofMaterial:
        scope = args[3]
        assert isinstance(scope, BrainReadScope)
        case.body_calls.append(scope)
        position = len(case.body_calls)
        if case.material_failure == position:
            raise AcceptanceDeniedError("nominated actual material READ/graph failure")
        if position == 2 and case.after_second is not None:
            case.after_second()
        return case.materials[position - 1]

    async def clock(_: AsyncSession) -> datetime:
        return case.clock["now"]

    monkeypatch.setattr(module, "read_strategy_proof_material_locked", body)
    monkeypatch.setattr(ManagementPlanStore, "current_binding", binding_read)
    monkeypatch.setattr(module, "revalidate_brain_scope", read_gate)
    monkeypatch.setattr(module, "require_cycle_native_partition", partitions)
    monkeypatch.setattr(module, "require_strategy_application_role", AsyncMock())
    monkeypatch.setattr(module, "db_now", clock)
    return case
