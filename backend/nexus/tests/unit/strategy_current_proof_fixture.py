"""Actual-shaped owner proof composition with genuine synthetic JWT and mocked native SQL."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID

import jwt
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_input_models import BrainArtifactResourceInput
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.directory_models import DirectoryCompany, DirectoryMembership
from nexus.company.management.acceptance import VerificationSpec, WorkAcceptance
from nexus.company.management.acceptance_models import (
    ManagementWorkAcceptance,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity, _verify
from nexus.company.strategy.acceptance import build_strategy_acceptance
from nexus.company.strategy.check_output import prepare_strategy_check
from nexus.company.strategy.contracts import (
    STRATEGY_CHECK_CRITERIA,
    STRATEGY_CHECK_RECIPE,
    StrategyBrief,
    StrategySelectionRef,
)
from nexus.company.strategy.current_proof_contracts import StrategyCurrentProof
from nexus.company.strategy.current_proof_reader import StrategyCurrentProofReader
from nexus.company.strategy.input_reader import StrategyInputReader
from nexus.company.strategy.owner_selection import describe_strategy_selection
from nexus.company.strategy.publication_contracts import PreparedStrategyPublication
from nexus.company.strategy.publication_protection import StrategyReadProtection
from nexus.company.strategy.verifier_facts import StrategyVerifierReceipt
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.tests.unit.strategy_current_proof_graph_fixture import add_check_rows
from nexus.tests.unit.strategy_current_proof_io_fixture import install_proof_reads
from nexus.tests.unit.strategy_current_proof_rows_fixture import saved_rows
from nexus.tests.unit.strategy_publication_reader_fixture import ReaderCase, reader_case
from nexus.tests.unit.strategy_verifier_receipt_fixture import _lease, _work


@dataclass
class ProofCase:
    base: ReaderCase
    service: StrategyCurrentProofReader
    credential: AuthenticatedWorkerIdentity
    scope: BrainReadScope
    record: WorkAcceptance
    selection: StrategySelectionRef
    company: DirectoryCompany
    member: DirectoryMembership
    pair: SimpleNamespace
    privileged: list[bool]
    actions: list[UUID]
    invalid: list[bool]
    body_gets: list[UUID]
    graph_calls: dict[str, int]
    check_ref: ArtifactRevisionRef
    verifier: StrategyVerifierReceipt
    final_deadline: list[datetime | None]
    owner_reads: list[int]

    @property
    def session(self) -> MagicMock:
        return self.base.source.session

    @property
    def reader(self) -> StrategyInputReader:
        return self.base.reader

    async def read(self) -> StrategyCurrentProof:
        return await self.service.load_locked(
            self.session,
            self.base.source.control,
            self.scope,
            self.credential.identity,
            self.selection,
            credential=self.credential,
        )

    def break_proof(self, which: str) -> None:
        company = self.scope.company_id
        action = self.verifier.action.action_id
        if which == "receipt":
            effect = cast(EffectIntent, self.base.rows[(EffectIntent, (company, action))])
            effect.receipt_json = self.verifier.receipt.model_copy(
                update={"task_id": UUID(int=999)}
            ).model_dump_json()
        elif which == "action":
            cast(JournalAction, self.base.rows[(JournalAction, action)]).proposal_hash = "b" * 64
        elif which == "attempt":
            cast(
                ExecutionAttempt,
                self.base.rows[
                    (ExecutionAttempt, (company, self.record.target.verifier.task_id, action))
                ],
            ).fence = 3
        elif which == "extra_action":
            self.actions.append(UUID(int=999))
        elif which == "no_action":
            self.actions.clear()
        elif which == "graph":
            self.base.edges[
                (
                    BrainArtifactResourceInput.__tablename__,
                    self.verifier.protected_result.artifact_revision_id,
                )
            ].clear()
        elif which == "bytes":
            cast(
                BrainArtifactRevision,
                self.base.rows[
                    (
                        BrainArtifactRevision,
                        (company, self.verifier.protected_result.artifact_revision_id),
                    )
                ],
            ).raw_text = "changed"
        else:
            self.invalid[0] = True

    def expire_at_final(self, which: str) -> None:
        now = self.base.source.clock["now"]
        deadline = (
            self.credential.expires_at if which == "credential" else now + timedelta(seconds=20)
        )
        self.final_deadline[0] = deadline
        original = self.base.reader._read_gate
        count = [0]

        async def gate(
            session: AsyncSession,
            control: CompanyControl,
            scope: BrainReadScope,
            identity: VerifiedIdentity,
            prepared: PreparedStrategyPublication,
            credential: AuthenticatedWorkerIdentity,
        ) -> StrategyReadProtection:
            value = await original(session, control, scope, identity, prepared, credential)
            count[0] += 1
            selected = (which == "initial" and count[0] == 1) or (
                which == "current" and count[0] == 2
            )
            grant = self.base.source.grant.model_copy(
                update={"expires_at": deadline if selected else None}
            )
            return replace(value, grants=(grant,), sources=replace(value.sources, grants=()))

        self.base.reader._read_gate = gate  # type: ignore[method-assign]


def _target(base: ReaderCase) -> VerificationSpec:
    original = base.prepared.original.snapshot
    receipt = ActionReceipt.model_validate_json(base.effect.receipt_json or "")
    return VerificationSpec(
        company_id=original.company_id,
        author=original.scope.author,
        verifier=original.scope.verifier,
        action_id=base.action.action_id,
        proposal_sha256=receipt.proposal_hash,
        receipt_id=receipt.receipt_id,
        receipt_sha256=canonical_sha256(receipt),
        work_snapshot_sha256=original.scope.author_registration_sha256,
        criterion_ids=STRATEGY_CHECK_CRITERIA,
        artifacts=(base.prepared.brief,),
        check_recipe=STRATEGY_CHECK_RECIPE,
    )


def proof_case(monkeypatch: pytest.MonkeyPatch) -> ProofCase:
    # This >50-line fixture keeps exact native rows, both graphs and real owner scope together.
    from nexus.company.strategy import input_reader
    from nexus.company.strategy.contracts import StrategyCheckInput

    base = reader_case(monkeypatch)
    source, prepared = base.source, base.prepared
    company_id, now = source.scope.company_id, source.clock["now"]
    bound = prepared.original.snapshot.scope.verifier
    owner = source.control.owner_id
    key = SecretStr("public-synthetic-owner-proof-fixture-key-not-a-real-credential-at-least64")
    credential = _verify(
        SecretStr(
            jwt.encode(
                {
                    "sub": str(owner),
                    "workspace_id": str(bound.workspace_id),
                    "iat": int(now.timestamp()) - 10,
                    "exp": int(now.timestamp()) + 300,
                },
                key.get_secret_value(),
                algorithm="HS256",
            )
        ),
        key,
    )
    scope = source.scope.model_copy(update={"principal_id": owner})
    company = DirectoryCompany(
        company_id=company_id,
        workspace_id=bound.workspace_id,
        owner_id=owner,
        company_active=True,
        workspace_active=True,
    )
    member = DirectoryMembership(
        company_id=company_id,
        principal_id=owner,
        role="owner",
        principal_active=True,
        membership_active=True,
    )
    base.rows[(DirectoryCompany, company_id)] = company
    base.rows[(DirectoryMembership, (company_id, owner))] = member
    target = _target(base)
    lease = _lease(target, now)
    work = _work(target, lease)
    work.state, work.lease_until = "eligible", None
    pair = input_reader.resolve_strategy_pair_locked.return_value  # type: ignore[attr-defined]
    pair.verifier = work
    base.rows[(ExecutionWork, (company_id, work.task_id))] = work
    manifest = GeneratedArtifactInputs(
        **prepared.original.snapshot.inputs.model_dump(
            exclude={"artifacts", "required_resource_ids"}
        ),
        artifacts=(
            *prepared.original.snapshot.inputs.artifacts,
            prepared.compiled.original_bundle.artifact,
            prepared.brief,
        ),
        required_resource_ids=(
            *prepared.original.snapshot.inputs.required_resource_ids,
            prepared.compiled.original_bundle.resource.resource_id,
        ),
    )
    command = StrategyCheckInput(
        company_id=company_id,
        target=target,
        output=prepared.brief,
        output_utf8=prepared.compiled.prepared.raw_bytes,
        snapshot=prepared.original.snapshot,
    )
    facts, ref, event = add_check_rows(base, target, manifest, command, now)
    record = build_strategy_acceptance(
        command,
        manifest,
        facts,
        prepare_strategy_check(command, manifest, "internal").raw_bytes,
        now,
    )
    brief = StrategyBrief.model_validate_json(prepared.compiled.prepared.raw_bytes)
    selection = describe_strategy_selection(brief, record, brief.candidates[0].scope.candidate_id)
    saved, proofs = saved_rows(record)
    base.rows[(ManagementWorkAcceptance, (company_id, record.acceptance_id))] = saved
    actions = [facts.action.action_id]
    invalid, privileged = [False], [False]
    body_gets: list[UUID] = []
    final_deadline: list[datetime | None] = [None]
    owner_reads = [0]
    graph_calls = {"B/S": 0, "C": 0}
    case = ProofCase(
        base,
        StrategyCurrentProofReader(base.reader),
        credential,
        scope,
        record,
        selection,
        company,
        member,
        pair,
        privileged,
        actions,
        invalid,
        body_gets,
        graph_calls,
        ref,
        facts,
        final_deadline,
        owner_reads,
    )

    install_proof_reads(case, proofs, event, manifest, monkeypatch)
    return case
