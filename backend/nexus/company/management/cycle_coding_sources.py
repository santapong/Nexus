"""Actual per-read C historical header owners, with no fresh execution or actor lookup."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_prepared_contracts import CodingHeaderRead
from nexus.company.management.coding_prepared_history import validate_history_locked
from nexus.company.management.coding_prepared_store import CodingPreparedStore
from nexus.company.management.coding_repository import CodingRepositoryReader
from nexus.company.management.planning_native_facts import clock_us, require_time
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.harness.journal_models import CompanyControl

if TYPE_CHECKING:
    from uuid import UUID

    from nexus.company.management.cycle_cost_contracts import NativeCostSelection
    from nexus.execution.coding_services import CodingServices


@dataclass(frozen=True, slots=True, eq=False)
class CodingCostProof:
    """Actual read identity is retained; copying these values conveys no source proof."""

    store: CodingPreparedStore
    read: CodingHeaderRead


class CodingCostSources:
    """One fixed original C graph; each owner history read has its own retained store."""

    def __init__(self, services: CodingServices) -> None:
        from nexus.execution.coding_services import CodingServices

        if type(services) is not CodingServices:
            raise ValueError("Coding financial sources require the actual configured C services")
        services.require_composition()
        self.services = services
        self._original = services
        self._pins = services._pins()
        self._stores: list[tuple[CodingPreparedStore, int]] = []
        self._issued: list[
            tuple[CodingCostProof, CompanyControlScope, AuthenticatedWorkerIdentity, str]
        ] = []

    def require_composition(self) -> None:
        if self.services is not self._original or self.services._pins() != self._pins:
            raise ManagementDeniedError("Original coding financial source graph changed")
        self.services.require_composition()

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        return tuple(
            dict.fromkeys(task for store, _ in self._stores for task in store.pending_owners())
        )

    @staticmethod
    def _fingerprint(proof: CodingCostProof) -> str:
        return "|".join(
            (
                canonical_sha256(proof.read.header),
                canonical_sha256(proof.read.reference),
                proof.read.source_signature,
                str(proof.read.read_end_us),
            )
        )

    def require_proof(
        self,
        proof: CodingCostProof,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        end_us: int,
    ) -> int:
        self.require_composition()
        end = min(end_us, proof.read.read_end_us)
        require_time(end)
        owner.require_time(datetime.now(UTC))
        original = next((row for row in self._issued if row[0] is proof), None)
        if (
            original is None
            or original[1] != scope
            or original[2] is not owner
            or original[3] != self._fingerprint(proof)
            or not any(store is proof.store for store, _ in self._stores)
        ):
            raise ManagementDeniedError("Coding finance requires its original owned header read")
        proof.store._current(owner, end)
        return end

    async def read(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        action_id: UUID,
        *,
        end_us: int,
    ) -> CodingCostProof:
        self.require_composition()
        require_time(end_us)
        services = self.services
        # This is an owner-only history reader. Execution may be stopped and its
        # C credential/endpoint unavailable; neither is consulted or renewed.
        self._stores[:] = [
            row for row in self._stores if row[1] > clock_us() or row[0].pending_owners()
        ]
        self._issued[:] = [row for row in self._issued if row[0].read.read_end_us > clock_us()]
        if len(self._stores) >= 32:
            raise ManagementDeniedError("Coding financial read-owner bound exceeded")
        store = CodingPreparedStore(
            services.factory,
            services.management,
            services.contexts,
            services.prepared_blobs,
            services.source_views,
            services.recipe,
            CodingRepositoryReader(services.repository_path, services.repository_selection),
        )
        self._stores.append((store, end_us))
        read = await store.read_history_header(scope, owner, action_id, end_us=end_us)
        proof = CodingCostProof(store, read)
        self._issued.append((proof, scope, owner, self._fingerprint(proof)))
        self.require_proof(proof, scope, owner, end_us)
        return proof

    async def validate_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        proof: CodingCostProof,
        expected: NativeCostSelection,
        end_us: int,
    ) -> tuple[str | None, int]:
        """No private IO or nested CC; native changes fail, source denial is unconfirmed."""
        from nexus.company.management.cycle_model_reader import native_cost_selection

        end = self.require_proof(proof, scope, owner, end_us)
        current = await native_cost_selection(
            session, scope.company_id, expected.action.proposal.action_id
        )
        if current != expected:
            raise ManagementDeniedError("Coding native financial history changed during read")
        try:
            selected, signature, end = await validate_history_locked(
                proof.store,
                session,
                control,
                scope,
                owner,
                expected.action.proposal.action_id,
                header=proof.read.header,
                end_us=end,
            )
        except TimeoutError:
            raise
        except ValueError:
            self.require_proof(proof, scope, owner, end)
            return None, end
        if selected != expected:
            raise ManagementDeniedError("Coding native financial snapshot changed")
        self.require_proof(proof, scope, owner, end)
        return signature if signature == proof.read.source_signature else None, end
