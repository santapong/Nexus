"""Actual owner transaction wrapper; no fabricated strategy actor, token, task or execute lease."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.contracts import StrategySelectionRef
from nexus.company.strategy.current_proof_contracts import StrategyCurrentProof
from nexus.company.strategy.current_proof_reader import StrategyCurrentProofReader
from nexus.company.strategy.publication_protection import require_credential
from nexus.execution.runtime_support import db_now


class StrategyOwnerProofReader:
    """Own one actual factory and concrete current proof reader; reads create no native work."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        reader: StrategyCurrentProofReader,
    ) -> None:
        require_acceptance(
            isinstance(reader, StrategyCurrentProofReader)
            and reader.reader.artifacts.factory is factory
        )
        self.factory, self.reader = factory, reader

    async def load(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        selection: StrategySelectionRef,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> StrategyCurrentProof:
        """Return current facts with their deadlines; no owner choice or transition is recorded."""
        current = BrainReadScope(
            company_id=scope.company_id,
            workspace_id=identity.workspace_id,
            principal_id=scope.principal_id,
            operation_id=scope.operation_id,
            trace_id=scope.trace_id,
        )
        async with management_owner_transaction(self.factory, scope, identity) as (
            session,
            control,
            _,
        ):
            require_credential(credential, identity, current, await db_now(session))
            result = await self.reader.load_locked(
                session, control, current, identity, selection, credential=credential
            )
            await require_brain_scope(session, control, current, identity, owner=True)
            now = await db_now(session)
            require_credential(credential, identity, current, now)
            result.require_time(now)
            return result
