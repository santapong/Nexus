"""Protected owner reconciliation provenance and immutable observed receipt binding."""

from __future__ import annotations

import hashlib
import json
from uuid import uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.execution.effect_support import effect_record, require_receipt_binding
from nexus.execution.owner_reconcile_contracts import (
    OwnerReconciliationLease,
    ReconciliationObservation,
)
from nexus.execution.runtime_contracts import EffectRecord, ExecutionDeniedError
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import lease_scope
from nexus.harness.journal_budget import reconcile_cost


def _bound_receipt(
    owned: OwnerReconciliationLease, observation: ReconciliationObservation
) -> ActionReceipt:
    proof, scope = observation.proof, owned.control_scope
    if scope.principal_id not in proof.allowed_principals:
        raise ExecutionDeniedError("Observed proof is inaccessible to the actual owner")
    payload = json.dumps(
        {
            "owner": str(scope.principal_id),
            "operation": str(scope.operation_id),
            "operation_trace": str(scope.trace_id),
            "fence": owned.execution.fence,
            "receipt": observation.receipt.model_dump(mode="json"),
            "actual_usd": str(observation.actual_usd),
            "proof": proof.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()
    provenance = ArtifactRef(
        company_id=scope.company_id,
        artifact_id=uuid5(scope.operation_id, "owner-reconciliation-provenance-v1"),
        reference=f"owner-reconciliation://{scope.principal_id}/{scope.operation_id}/{scope.trace_id}/{owned.execution.fence}",
        sha256=digest,
        revision="owner-reconciliation-v1",
        allowed_principals=(scope.principal_id,),
    )
    return ActionReceipt.model_validate(
        observation.receipt.model_dump()
        | {
            "artifacts": (*observation.receipt.artifacts, proof, provenance),
        }
    )


async def record_observation(
    session: AsyncSession,
    work: ExecutionWork,
    effect: EffectIntent,
    owned: OwnerReconciliationLease,
    observation: ReconciliationObservation,
) -> EffectRecord:
    observation = ReconciliationObservation.model_validate_json(observation.model_dump_json())
    require_receipt_binding(effect, observation.receipt)
    if observation.receipt.outcome == "outcome_unknown":
        return effect_record(effect)
    if effect.state not in {"intent", "outcome_unknown"}:
        raise ExecutionDeniedError("Issued outcome changed while resolving evidence")
    if effect.receipt_json is not None:
        prior = ActionReceipt.model_validate_json(effect.receipt_json)
        if prior.external_id is not None and prior.external_id != observation.receipt.external_id:
            raise ExecutionDeniedError(
                "Observed external reference conflicts with prior issued evidence"
            )
    receipt = _bound_receipt(owned, observation)
    effect.receipt_json, effect.state = receipt.model_dump_json(), receipt.outcome
    work.state = "verifying" if receipt.outcome == "succeeded" else "blocked"
    await reconcile_cost(
        session, lease_scope(owned.execution), effect.action_id, observation.actual_usd
    )
    await session.flush()
    return effect_record(effect)
