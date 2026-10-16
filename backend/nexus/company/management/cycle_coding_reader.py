"""Protected C result billing joins using actual original owner/header/native proof."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nexus.company.access import CompanyControlScope
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.cycle_cost_contracts import (
    ModelCostRead,
    ModelSourceProof,
    NativeCostSelection,
)
from nexus.company.management.cycle_model_facts import join_cycle_model_fact
from nexus.company.management.cycle_model_native import native_model_artifact
from nexus.company.management.planning_native_facts import require_time
from nexus.company.management.planning_prepared_contracts import PlanningModelParameters
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity

if TYPE_CHECKING:
    from nexus.company.management.cycle_coding_sources import CodingCostProof
    from nexus.company.management.cycle_model_reader import CycleModelReader


async def _gate(
    parent: CycleModelReader,
    scope: CompanyControlScope,
    owner: AuthenticatedWorkerIdentity,
    proof: CodingCostProof,
    selected: NativeCostSelection,
    end: int,
) -> tuple[str | None, int]:
    assert parent.coding is not None
    async with management_owner_transaction(
        parent.factory, scope, owner.identity, allow_paused=True
    ) as (
        session,
        control,
        _,
    ):
        parent._owner(scope, owner, control, end)
        signature, end = await parent.coding.validate_locked(
            session, control, scope, owner, proof, selected, end
        )
        parent._owner(scope, owner, control, end)
    parent.require_composition()
    require_time(end)
    return signature, end


async def read_coding_cost(
    parent: CycleModelReader,
    scope: CompanyControlScope,
    owner: AuthenticatedWorkerIdentity,
    selected: NativeCostSelection,
    *,
    end_us: int,
) -> ModelCostRead:
    """Known, failed or invalid generated content keeps its independently joined bill."""
    assert parent.coding is not None
    parent.require_composition()
    end = end_us
    action = selected.action.proposal
    try:
        parameters = PlanningModelParameters.model_validate_json(json.dumps(action.parameters))
    except ValueError:
        return parent._partial(owner, end, "native_model_parameters_invalid")
    artifact = native_model_artifact(scope, selected, parameters)
    if artifact is None:
        return parent._partial(owner, end, "model_record_not_readable")
    try:
        proof = await parent.owned(
            parent.coding.read(scope, owner, action.action_id, end_us=end), end
        )
    except TimeoutError:
        raise
    except (ValueError, OSError):
        return parent._partial(owner, end, "source_proof_unavailable")
    end = min(end, proof.read.read_end_us)
    signature, end = await parent.owned(_gate(parent, scope, owner, proof, selected, end), end)
    if signature is None:
        return parent._partial(owner, end, "source_read_changed")
    try:
        before = await parent.owned(
            asyncio.to_thread(parent._physical, artifact, action.action_id, parameters.request_id),
            end,
        )
        record = await parent.owned(parent.evidence.load_record(artifact), end)
        evidence = record.evidence
        after = await parent.owned(
            asyncio.to_thread(parent._physical, artifact, action.action_id, parameters.request_id),
            end,
        )
        if before != after:
            return parent._partial(owner, end, "model_record_changed")
    except TimeoutError:
        raise
    except (ValueError, OSError):
        return parent._partial(owner, end, "protected_record_unavailable")
    signature, end = await parent.owned(_gate(parent, scope, owner, proof, selected, end), end)
    if signature is None:
        return parent._partial(owner, end, "source_read_changed")
    header = proof.read.header
    whole = evidence.input_estimate.whole_request
    if (
        evidence.request_hash != header.request_sha256
        or evidence.owner_id != header.owner_id
        or evidence.request.registry_id != header.parameters.registry_id
        or canonical_sha256(evidence.recipe) != header.input_recipe_sha256
        or canonical_sha256(evidence.model) != header.model_sha256
        or canonical_sha256(parent.catalog.models) != header.registry_sha256
        or whole is None
        or whole.registry_sha256 != header.registry_sha256
        or whole.model_sha256 != header.model_sha256
    ):
        return parent._partial(owner, end, "prepared_model_mismatch")
    work = selected.directory.work
    assert work is not None
    fact = join_cycle_model_fact(
        selected.directory.directory_data(),
        work,
        selected.action,
        evidence.request,
        parent.coding.services.recipe,
        parent.catalog.models,
        attempt=selected.attempt.native_data() if selected.attempt else None,
        intent=selected.intent,
        hold=selected.hold.native_data() if selected.hold else None,
        artifact=artifact,
        evidence=evidence,
        wire=record.wire,
    )
    fact.model_dump_json()
    require_time(end)
    owner.require_time(datetime.now(UTC))
    parent.coding.require_proof(proof, scope, owner, end)
    parent.require_composition()
    return ModelCostRead(
        fact, fact.blockers, end, signature, ModelSourceProof(selected, None, signature, proof)
    )
