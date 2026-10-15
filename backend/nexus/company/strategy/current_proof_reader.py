"""Concrete same-session Strategy proof under the actual taskless company owner."""

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.application_role import require_strategy_application_role
from nexus.company.strategy.contracts import StrategySelectionRef
from nexus.company.strategy.current_proof_contracts import StrategyCurrentProof
from nexus.company.strategy.current_proof_read import (
    StrategyProofMaterial,
    assemble_strategy_current_proof,
    read_strategy_proof_material_locked,
)
from nexus.company.strategy.input_reader import StrategyInputReader
from nexus.company.strategy.publication_protection import require_credential
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


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


class StrategyCurrentProofReader:
    """Owner-only current proof; material reuse does not confer owner authority."""

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
    ) -> StrategyProofMaterial:
        return await read_strategy_proof_material_locked(
            self.reader, session, control, scope, identity, selection, credential
        )

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
        """Both full reads retain first fences/windows through final actual owner checks."""
        selection = StrategySelectionRef.model_validate(selection.model_dump(warnings=False))
        require_acceptance(
            selection.company_id == scope.company_id == self.reader.catalog.company_id
        )
        await _owner(session, control, scope, identity, credential)
        first = await self._read(session, control, scope, identity, selection, credential)
        current = await self._read(session, control, scope, identity, selection, credential)
        await _owner(session, control, scope, identity, credential)
        return assemble_strategy_current_proof(
            selection, first, current, credential, scope, identity, await db_now(session)
        )
