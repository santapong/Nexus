"""Concrete same-session current Strategy proof, read under the actual taskless company owner."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.acceptance import build_strategy_acceptance
from nexus.company.strategy.application_role import require_strategy_application_role
from nexus.company.strategy.check_output import require_strategy_check_bytes
from nexus.company.strategy.contracts import StrategyBrief, StrategySelectionRef
from nexus.company.strategy.current_proof_contracts import StrategyCurrentProof
from nexus.company.strategy.current_proof_material import (
    load_current_material_locked,
    protect_current_check_locked,
)
from nexus.company.strategy.current_proof_rows import load_selected_acceptance_locked
from nexus.company.strategy.input_reader import StrategyInputReader
from nexus.company.strategy.owner_selection import describe_strategy_selection
from nexus.company.strategy.publication_protection import (
    StrategyCheckMaterial,
    StrategyProtectedPublication,
    require_credential,
)
from nexus.company.strategy.verifier_facts import (
    StrategyVerifierReceipt,
    require_strategy_verifier_facts_locked,
)
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


@dataclass(frozen=True)
class _ProofRead:
    record: WorkAcceptance
    material: StrategyCheckMaterial
    original: StrategyProtectedPublication
    facts: StrategyVerifierReceipt
    raw: bytes


async def _owner(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    credential: AuthenticatedWorkerIdentity,
) -> None:
    require_acceptance(
        session.in_transaction()
        and not control.paused
        and control.company_id == scope.company_id
        and scope.principal_id == control.owner_id
        and (scope.task_id, scope.task_trace_id, scope.actor_id) == (None, None, None)
    )
    await require_strategy_application_role(session)
    require_credential(credential, identity, scope, await db_now(session))
    await require_brain_scope(session, control, scope, identity, owner=True)


async def _verifier_action(session: AsyncSession, material: StrategyCheckMaterial) -> UUID:
    binding = material.command.target.verifier
    values = tuple(
        (
            await session.scalars(
                select(EffectIntent.action_id)
                .where(
                    EffectIntent.company_id == binding.company_id,
                    EffectIntent.task_id == binding.task_id,
                    EffectIntent.trace_id == binding.trace_id,
                    EffectIntent.run_id == binding.run_id,
                    EffectIntent.attempt_kind == "tool_attempts",
                )
                .limit(2)
            )
        ).all()
    )
    require_acceptance(len(values) == 1)
    return values[0]


class StrategyCurrentProofReader:
    """One server-owned reader composition; supplied selections and PASS values grant no READ."""

    def __init__(self, reader: StrategyInputReader) -> None:
        require_acceptance(isinstance(reader, StrategyInputReader))
        self.reader = reader

    async def _read(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        selection: StrategySelectionRef,
        credential: AuthenticatedWorkerIdentity,
    ) -> _ProofRead:
        # Keep this >50-line complete native proof/graph/read comparison in one operation.
        record = await load_selected_acceptance_locked(session, selection)
        material, original = await load_current_material_locked(
            self.reader,
            session,
            control,
            scope,
            identity,
            record.target.action_id,
            credential=credential,
        )
        require_acceptance(material.command.target == record.target)
        action_id = await _verifier_action(session, material)
        facts = await require_strategy_verifier_facts_locked(
            session,
            control,
            scope,
            identity,
            material.protection.pair.verifier,
            material.command.target,
            verifier_action_id=action_id,
            protected_result=record.proofs[0].result_artifact,
            rule=self.reader.rules.check,
            artifacts=self.reader.artifacts,
            credential=credential,
        )
        raw = await protect_current_check_locked(
            self.reader, session, control, scope, identity, material, facts, credential=credential
        )
        require_acceptance(
            build_strategy_acceptance(
                material.command, material.inputs, facts, raw, record.recorded_at
            )
            == record
        )
        brief = StrategyBrief.model_validate_json(
            original.publication.prepared.compiled.prepared.raw_bytes
        )
        require_acceptance(
            describe_strategy_selection(brief, record, selection.candidate_id) == selection
        )
        return _ProofRead(record, material, original, facts, raw)

    async def load_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        selection: StrategySelectionRef,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> StrategyCurrentProof:
        """Re-read original/current proof in the existing CompanyControl-first owner transaction."""
        # Both complete read captures must survive every later await to the final owner clock.
        selection = StrategySelectionRef.model_validate(selection.model_dump(warnings=False))
        require_acceptance(
            selection.company_id == scope.company_id == self.reader.catalog.company_id
        )
        await _owner(session, control, scope, identity, credential)
        first = await self._read(session, control, scope, identity, selection, credential)
        first_fences = (
            first.material.protection.pair.author.fence,
            first.material.protection.pair.verifier.fence,
        )
        current = await self._read(session, control, scope, identity, selection, credential)
        require_acceptance(
            (
                current.record,
                current.original.publication,
                current.material.command,
                current.material.inputs,
                current.facts,
                current.raw,
            )
            == (
                first.record,
                first.original.publication,
                first.material.command,
                first.material.inputs,
                first.facts,
                first.raw,
            )
        )
        require_acceptance(
            first_fences
            == (
                current.material.protection.pair.author.fence,
                current.material.protection.pair.verifier.fence,
            )
        )
        assert current.material.command.output_utf8 is not None
        brief = StrategyBrief.model_validate_json(current.material.command.output_utf8)
        checked = require_strategy_check_bytes(
            current.material.command,
            current.material.inputs,
            current.facts.protected_result,
            current.raw,
        )
        await _owner(session, control, scope, identity, credential)
        now = await db_now(session)
        require_acceptance(current.record.recorded_at <= now)
        first.material.protection.require_time(now)
        current.material.protection.require_time(now)
        require_credential(credential, identity, scope, now)
        return StrategyCurrentProof(
            selection,
            current.original.publication,
            current.record,
            brief,
            current.facts,
            checked,
            current.original.publication.original_intent_fence,
            first_fences[0],
            first_fences[1],
            first.material.protection,
            current.material.protection,
            now,
        )
