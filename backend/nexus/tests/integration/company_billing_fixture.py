"""Protected synthetic invoice bytes, not real provider usage or a user supplied verdict."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.execution.billing_contracts import (
    BillingLookupRequest,
    BillingObservation,
    observation_digest,
)
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_store import ExecutionStore
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import (
    WORKER,
    action,
    identity,
    ready,
    receipt,
    scope,
)


class ProtectedInvoiceResolver:
    """Configured exact mapping, bounded actual file reads and an authoritative test ACL index."""

    def __init__(self, path: Path, proof: ArtifactRef, receipt_hash: str) -> None:
        self.path, self.proof, self.receipt_hash = path, proof, receipt_hash
        self.allowed_principals = proof.allowed_principals
        self.current_proof_hash = proof.sha256
        self.calls = 0
        self.verified_observation_hash: str | None = None

    async def resolve(self, request: BillingLookupRequest) -> BillingObservation | None:
        self.calls += 1
        if (
            request.lease.control_scope.principal_id not in self.allowed_principals
            or self.proof.sha256 != self.current_proof_hash
        ):
            return None
        if request.receipt_hash != self.receipt_hash:
            raise ExecutionDeniedError("Protected invoice mapping differs from known receipt")
        try:
            data = await asyncio.to_thread(self._read_bounded)
        except OSError:
            return None
        if hashlib.sha256(data).hexdigest() != self.proof.sha256:
            return None
        payload = json.loads(data)
        observation = BillingObservation.model_validate(
            payload
            | {
                "receipt_hash": request.receipt_hash,
                "proof": self.proof,
                "source_checked_at": datetime.now(UTC),
            }
        )
        self.verified_observation_hash = observation_digest(observation)
        return observation

    def _read_bounded(self) -> bytes:
        with self.path.open("rb") as stream:
            data = stream.read(32_769)
        if len(data) > 32_768:
            raise ValueError("Protected invoice exceeds the configured bounded read")
        return data

    async def validate_before_commit(
        self,
        session: AsyncSession,
        request: BillingLookupRequest,
        observation: BillingObservation,
        now: datetime,
    ) -> None:
        """No external I/O; future adapters replace this protected-index check with DB ACLs."""
        assert session.in_transaction() and now.utcoffset() is not None
        if (
            OWNER not in self.allowed_principals
            or observation.proof != self.proof
            or observation.proof.sha256 != self.current_proof_hash
            or request.receipt_hash != self.receipt_hash
            or observation.proof not in request.receipt.artifacts
            or observation_digest(observation) != self.verified_observation_hash
        ):
            raise ExecutionDeniedError("Protected source ACL/hash or exact receipt mapping changed")


async def known_unknown_bill(
    factory: async_sessionmaker[AsyncSession],
    path: Path,
    amount: str,
    *,
    outcome: str = "succeeded",
) -> tuple[ExecutionStore, ActionProposal, ProtectedInvoiceResolver]:
    execution, effects = await ready(factory)
    proposal = await action(factory)
    lease = await execution.claim(scope(), identity(), WORKER)
    await effects.begin(lease, identity(), proposal.action_id)
    result = receipt(proposal, outcome=outcome)
    invoice = {
        "company_id": str(COMPANY),
        "evidence_id": str(uuid5(proposal.action_id, "synthetic-invoice-v1")),
        "action_id": str(proposal.action_id),
        "task_id": str(result.task_id),
        "trace_id": str(result.trace_id),
        "run_id": str(lease.run_id),
        "receipt_id": str(result.receipt_id),
        "proposal_hash": result.proposal_hash,
        "external_id": result.external_id,
        "price_version": proposal.price_version,
        "currency": "USD",
        "provider": "synthetic.invoice.provider",
        "source_observation_id": str(proposal.action_id),
        "provider_reference": result.external_id,
        "invoice_reference": f"synthetic-invoice:{proposal.action_id}",
        "actual_usd": amount,
        "observed_at": result.recorded_at.isoformat(),
    }
    data = json.dumps(invoice, sort_keys=True, separators=(",", ":")).encode()
    invoice_path = path / "protected-invoice.json"
    await asyncio.to_thread(invoice_path.write_bytes, data)
    proof = ArtifactRef(
        company_id=COMPANY,
        artifact_id=uuid5(proposal.action_id, "synthetic-invoice-artifact-v1"),
        reference=str(invoice_path),
        sha256=hashlib.sha256(data).hexdigest(),
        revision="invoice-fixture-v1",
        allowed_principals=(OWNER,),
    )
    result = type(result).model_validate(result.model_dump() | {"artifacts": (proof,)})
    await effects.record_receipt(lease, identity(), result, actual_usd=None)
    digest = hashlib.sha256(result.model_dump_json().encode()).hexdigest()
    return execution, proposal, ProtectedInvoiceResolver(invoice_path, proof, digest)
