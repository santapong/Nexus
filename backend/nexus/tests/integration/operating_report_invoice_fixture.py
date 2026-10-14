"""Actual protected invoice bytes feed public owner billing; no SQL operative evidence insert."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.execution.billing_contracts import BillingLookupRequest, BillingObservation
from nexus.execution.owner_billing_store import OwnerBillingStore
from nexus.harness.journal_models import CostHold
from nexus.tests.integration.management_acceptance_source_fixture import Policies, protected_text
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity


@dataclass(frozen=True)
class InvoiceReader:
    artifacts: BoundedArtifactReader
    reference: ArtifactRevisionRef
    proof_artifact_id: UUID | None = None

    async def resolve(self, request: BillingLookupRequest) -> BillingObservation:
        value = await self.artifacts.bounded_artifact(
            owner_scope(),
            identity(OWNER),
            self.reference.artifact_revision_id,
            start_byte=0,
            max_bytes=16384,
            include_history=False,
        )
        invoice = json.loads(value.text)
        receipt, lease = request.receipt, request.lease
        return BillingObservation(
            company_id=request.company_id,
            evidence_id=UUID(invoice["evidence_id"]),
            action_id=receipt.action_id,
            task_id=receipt.task_id,
            trace_id=receipt.trace_id,
            run_id=lease.execution.run_id,
            receipt_id=receipt.receipt_id,
            receipt_hash=request.receipt_hash,
            proposal_hash=receipt.proposal_hash,
            external_id=receipt.external_id,
            price_version=request.proposal.price_version,
            currency="USD",
            provider="offline.protected-invoice.v1",
            source_observation_id=invoice["source_observation_id"],
            provider_reference=receipt.external_id,
            invoice_reference=invoice["invoice_reference"],
            actual_usd=Decimal(invoice["actual_usd"]),
            proof=ArtifactRef(
                company_id=COMPANY,
                artifact_id=self.proof_artifact_id or self.reference.artifact_id,
                reference="protected:actual-invoice",
                sha256=self.reference.sha256,
                revision=self.reference.revision,
                allowed_principals=(OWNER,),
            ),
            observed_at=datetime.fromisoformat(invoice["observed_at"]),
            source_checked_at=datetime.now(UTC),
        )

    async def validate_before_commit(
        self,
        session: AsyncSession,
        request: BillingLookupRequest,
        observation: BillingObservation,
        now: datetime,
    ) -> None:
        from nexus.harness.journal_models import CompanyControl

        current = await session.get(CompanyControl, COMPANY)
        assert current is not None
        await self.artifacts.revalidate_artifact_reference(
            session,
            current,
            owner_scope(),
            identity(OWNER),
            self.reference,
            now,
        )
        require_acceptance(
            observation.proof.sha256 == self.reference.sha256
            and observation.proof.artifact_id
            == (self.proof_artifact_id or self.reference.artifact_id)
        )


async def publish_selected_invoice(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    policies: Policies,
    artifacts: BoundedArtifactReader,
    *,
    proof_artifact_id: UUID | None = None,
) -> None:
    async with brain_transaction(factory, owner_scope(), identity(OWNER)) as (session, _, _):
        hold = await session.scalar(
            select(CostHold).where(CostHold.company_id == COMPANY, CostHold.state == "unknown")
        )
        assert hold is not None
        task_id, action_id = hold.task_id, hold.action_id
    raw = json.dumps(
        {
            "evidence_id": str(uuid4()),
            "source_observation_id": str(uuid4()),
            "invoice_reference": "offline-observed-invoice-1",
            "actual_usd": "0.019000",
            "observed_at": datetime.now(UTC).isoformat(),
        }
    )
    proof = await protected_text(
        factory,
        ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1"),
        policies,
        raw,
        400,
    )
    owner = OwnerBillingStore(factory, InvoiceReader(artifacts, proof, proof_artifact_id), 10)
    lease = await owner.claim(control(), identity(OWNER), task_id, uuid4(), action_id)
    result = await owner.resolve(lease, identity(OWNER))
    assert result is not None and result.actual_usd == Decimal("0.019000")
    assert await owner.resolve(lease, identity(OWNER)) == result
    await owner.release(lease, identity(OWNER))
