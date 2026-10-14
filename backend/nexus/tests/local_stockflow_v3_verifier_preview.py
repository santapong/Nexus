"""Read-only actual verifier admission/current protected author output; no synthetic lease."""

from __future__ import annotations

import asyncio
import hashlib
import json
from uuid import uuid4

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.lifecycle import PlanRevision
from nexus.execution.management_checks import require_management_execution
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import execution_row, runtime_transaction
from nexus.harness.journal_contracts import LedgerScope
from nexus.settings import settings
from nexus.tests.integration.management_acceptance_source_fixture import Policies
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.local_stockflow_packet import ROOT, write_private
from nexus.tests.local_stockflow_v3_prepare import V3_ROOT
from nexus.tests.management_plan_support import VERIFIER
from nexus.tests.stockflow_packet_contracts import PreparedState


async def preview() -> None:
    state = PreparedState.model_validate_json(
        await asyncio.to_thread((V3_ROOT / "native-state.json").read_bytes)
    )
    revision = json.loads(
        await asyncio.to_thread((V3_ROOT / "sibling-revision-receipt.json").read_bytes)
    )
    plan = PlanRevision.model_validate_json(json.dumps(revision["approved"]))
    binding = plan.payload.children[-1].binding
    observed = json.loads(
        await asyncio.to_thread((V3_ROOT / "verified-result-observation.json").read_bytes)
    )
    reference = ArtifactRevisionRef.model_validate_json(json.dumps(observed["protected_ref"]))
    url = make_url(settings.company_test_database_url)
    if url.database != "nexus_company_test_builder":
        raise ValueError("Only retained builder database supported")
    engine = create_async_engine(url.set(username="nexus_company_app"))
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        scope = LedgerScope(
            company_id=binding.company_id,
            task_id=binding.task_id,
            trace_id=binding.trace_id,
            principal_id=VERIFIER,
        )
        policies = Policies()
        policies.values[state.source_policy.source_symbol] = state.source_policy
        artifacts = BoundedArtifactReader(
            factory, ProtectedBlobStore(ROOT, storage_symbol="fixture.blobs.v1")
        )
        freshness = RegisteredSourceFreshness(factory, policies)
        before = await ExecutionStore(factory).get(scope, identity(VERIFIER))
        async with runtime_transaction(factory, scope, identity(VERIFIER)) as (session, control, _):
            work = await execution_row(session, scope)
            await require_management_execution(
                session, control, work, identity(VERIFIER), state.catalog, artifacts, freshness
            )
        read_scope = BrainReadScope(
            company_id=binding.company_id,
            workspace_id=binding.workspace_id,
            principal_id=VERIFIER,
            operation_id=uuid4(),
            trace_id=uuid4(),
            task_id=binding.task_id,
            task_trace_id=binding.trace_id,
            actor_id=binding.actor_id,
        )
        body = await artifacts.bounded_artifact(
            read_scope,
            identity(VERIFIER),
            reference.artifact_revision_id,
            start_byte=0,
            max_bytes=16384,
            include_history=False,
        )
        if (
            body.artifact != reference
            or body.source_state != "current"
            or hashlib.sha256(body.text.encode()).hexdigest() != reference.sha256
        ):
            raise ValueError("Current actual verifier protected author output differs")
        after = await ExecutionStore(factory).get(scope, identity(VERIFIER))
        if before != after:
            raise ValueError("Read-only verifier preview changed native state")
        result = {
            "scope": "actual unused verifier management gate/current-source READ preview only",
            "verification": plan.payload.verification[-1].model_dump(mode="json"),
            "verifier": before.model_dump(mode="json"),
            "actual_gate_passed": True,
            "author_protected": reference.model_dump(mode="json"),
            "source_state": body.source_state,
            "no_state_changes": True,
            "new_claims": 0,
            "new_actions": 0,
            "new_processes": 0,
            "work_acceptance": "not supported by this report.check.v1 binding",
        }
        await asyncio.to_thread(
            write_private,
            V3_ROOT / "verifier-read-preview.json",
            json.dumps(result, indent=2).encode(),
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(preview())
