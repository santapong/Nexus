"""One opt-in production owner application/recovery proof, never a business-cycle claim.

Cohesion exception: this sequential retained-DB scenario keeps the actual HTTP,
protected packet, interruption, cold graph, queue, SDK mock and conserved native
outcomes together. Synthetic eligibility is NOT genuine model quality. No live
provider, builder, email, Pi, preview, database reset or process-restart claim.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from litestar.testing import AsyncTestClient

from nexus.builder.contained_query import clock_us
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.planning_prepared_contracts import prepared_reference
from nexus.execution.planning_application import planning_app
from nexus.execution.planning_application_runtime import (
    PlanningWorkerRuntime,
    capture_planning_worker_runtime,
    drain_planning_application,
    start_planning_application_worker,
)
from nexus.execution.planning_dispatch import PlanningDispatchRecord
from nexus.execution.planning_lifecycle_contracts import (
    PlanningCandidateReview,
    PlanningLifecycleStatus,
)
from nexus.execution.planning_owner_reads import PlanningInputReader, PlanningInputReview
from nexus.execution.planning_preparation import PreparedPlanningAction
from nexus.execution.planning_worker import PlanningSegmentResult, execute_planning_segment
from nexus.execution.runtime_store import ExecutionStore
from nexus.tests.integration.nexus_planning_application_fixture import (
    DATABASE,
    Case,
    Database,
    Probe,
    conserved,
    open_database,
    prepare_case,
    revoke_document,
)
from nexus.tests.integration.nexus_planning_runtime_fixture import (
    COMPANY,
    DOCUMENT_COMMIT,
    DOCUMENT_SHA256,
    key,
    owner_scope,
)
from nexus.tests.integration.test_nexus_planning_runtime import denied_builder, queue_row, result
from nexus.tests.unit.test_company_provider_conformance import KEY


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    """The exact future Root-created DB only; collection never opens it."""
    async for value in open_database():
        yield value


async def test_production_owner_application_cold_wait_recovery_and_same_root_plan(
    database: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Cohesion exception: this one supervised sequence preserves the actual order
    # and one-use publication/dispatch/model boundary instead of resetting a DB.
    started = datetime.now(UTC)
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    case: Case = await prepare_case(database, root, monkeypatch)
    probe = Probe()
    probe.install(monkeypatch)
    first = case.compose(database)
    app = first
    runtime: PlanningWorkerRuntime | None = None
    outcomes: list[PlanningSegmentResult] = []
    sent: PlanningDispatchRecord | None = None
    revised: PlanRevision | None = None
    recovered: PreparedPlanningAction | None = None
    base_url = f"/api/v2/companies/{COMPANY}"
    goal_url = base_url + f"/planning/goals/{case.config.goal.goal_id}"
    selected: dict[str, object] = {
        "goal": case.config.goal.model_dump(mode="json"),
        "expected_current_revision_id": None,
    }
    try:
        async with AsyncTestClient(planning_app(first), raise_server_exceptions=False) as client:
            assert (await client.get(goal_url + "/status")).status_code == 401
            assert (
                await client.get(goal_url + "/status", headers=case.member_headers)
            ).status_code == 403
            initial = await client.get(goal_url + "/status", headers=case.headers)
            assert initial.status_code == 200
            assert PlanningLifecycleStatus.model_validate_json(initial.content).bootstrap is None
            stale = case.config.goal.model_copy(update={"sha256": "f" * 64})
            assert (
                await client.post(
                    goal_url + "/bootstrap",
                    headers=case.headers,
                    json=selected | {"goal": stale.model_dump(mode="json")},
                )
            ).status_code == 403
            proposed = await client.post(
                goal_url + "/bootstrap", headers=case.headers, json=selected
            )
            assert proposed.status_code == 200
            base = PlanRevision.model_validate_json(proposed.content)
            assert base.revision == 1 and base.payload == case.ready.admission.payload("planning")
            assert (
                await client.post(
                    goal_url + "/prepare",
                    headers=case.headers,
                    json=selected | {"expected_current_revision_id": str(base.plan_revision_id)},
                )
            ).status_code == 403
            approve_url = base_url + f"/management/plans/{base.plan_revision_id}/approve"
            approved = await client.post(
                approve_url,
                headers=case.headers,
                json={
                    "exact_hash": base.sha256,
                    "expected_current_revision_id": str(base.plan_revision_id),
                },
            )
            assert approved.status_code == 200
            assert (
                await client.post(
                    goal_url + "/prepare",
                    headers=case.headers,
                    json=selected | {"expected_current_revision_id": str(key("stale-head"))},
                )
            ).status_code == 403
            with monkeypatch.context() as interruption:
                interruption.setattr(
                    ExecutionStore, "await_approval", probe.interrupt(database, first)
                )
                failed = await client.post(
                    goal_url + "/prepare",
                    headers=case.headers,
                    json=selected | {"expected_current_revision_id": str(base.plan_revision_id)},
                )
            assert failed.status_code == 500 and probe.pending is not None
            assert probe.pending_hash is not None and not probe.posts
            assert not first.lifecycle.pending_owners()
        # A new production graph reads actual stored r1 and exact immutable bytes.
        # This is deliberately cold recomposition in one process, not a restart claim.
        app = case.compose(database)
        assert app is not first and app.runtime.prepared is not first.runtime.prepared
        action = probe.pending
        assert action is not None and probe.pending_hash is not None
        action_url = base_url + f"/planning/actions/{action.action_id}"
        saved = await app.runtime.prepared.load_owner(
            owner_scope(case.ready.admission),
            case.owner.identity,
            action.action_id,
            end_us=clock_us() + 30_000_000,
        )
        assert saved.reference == prepared_reference(action)
        assert saved.prepared.request_sha256 == action.parameters["request_hash"]
        recovery_json = {
            "goal": case.config.goal.model_dump(mode="json"),
            "expected_current_revision_id": str(base.plan_revision_id),
            "expected_hash": probe.pending_hash,
        }
        async with AsyncTestClient(planning_app(app), raise_server_exceptions=True) as client:
            recovered_http = await client.post(
                action_url + "/recover-wait", headers=case.headers, json=recovery_json
            )
            assert recovered_http.status_code == 200
            recovered = PreparedPlanningAction.model_validate_json(recovered_http.content)
            assert recovered.action.proposal == action
            assert recovered.action.proposal_hash == probe.pending_hash
            assert recovered.reference == saved.reference
            assert recovered.work.state == "awaiting_approval" and recovered.work.worker_id is None
            assert recovered.work.counters.model_requests == 0 and not probe.posts
            restored = await client.post(
                action_url + "/recover-wait", headers=case.headers, json=recovery_json
            )
            assert restored.status_code == 200
            assert PreparedPlanningAction.model_validate_json(restored.content) == recovered
            assert (await client.get(action_url + "/input")).status_code == 401
            assert (
                await client.get(action_url + "/input", headers=case.member_headers)
            ).status_code == 403
            viewed = await client.get(action_url + "/input", headers=case.headers)
            assert viewed.status_code == 200 and viewed.headers["cache-control"] == "no-store"
            review = PlanningInputReview.model_validate_json(viewed.content)
            assert review.prepared == saved.prepared
            assert review.prepared.input_estimate and review.prepared.input_estimate.whole_request
            assert review.prepared.input_estimate.total_tokens == 400_000
            assert review.maximum_reservation_usd == recovered.quote.amount_usd
            assert review.prepared.context.manifest.inclusions
            assert "Nexus" in review.prepared.request.input_text
            assert KEY not in viewed.text and str(root) not in viewed.text
            generic = await client.get(
                base_url + f"/management/actions/{action.action_id}/review", headers=case.headers
            )
            assert generic.status_code == 200 and generic.json()["availability"] == "available"
            wrong = case.ready.catalog.models.model_copy(
                update={
                    "models": (
                        case.ready.catalog.models.models[0].model_copy(
                            update={"model_id": "crossed-model"}
                        ),
                    )
                }
            )
            with pytest.raises(ValueError, match="original registry/model"):
                await PlanningInputReader(app.runtime.prepared, wrong).input(
                    owner_scope(case.ready.admission),
                    case.owner.identity,
                    action.action_id,
                    end_us=clock_us() + 30_000_000,
                )
            with pytest.raises(TimeoutError):
                await app.planning.reads.input(
                    owner_scope(case.ready.admission),
                    case.owner.identity,
                    action.action_id,
                    end_us=clock_us() - 1,
                )
            planner = case.ready.admission.slots[0].child.binding
            decision_url = base_url + f"/work/{planner.task_id}/actions/{action.action_id}/decision"
            assert (
                await client.post(
                    decision_url,
                    headers=case.headers,
                    json={
                        "trace_id": str(planner.trace_id),
                        "expected_hash": "f" * 64,
                        "approved": True,
                    },
                )
            ).status_code == 409
            decided = await client.post(
                decision_url,
                headers=case.headers,
                json={
                    "trace_id": str(planner.trace_id),
                    "expected_hash": probe.pending_hash,
                    "approved": True,
                },
            )
            assert decided.status_code == 200 and not probe.posts
            status = await client.get(goal_url + "/status", headers=case.headers)
            assert status.status_code == 200
            assert (
                PlanningLifecycleStatus.model_validate_json(status.content).owner_decision
                == "approved"
            )
            assert (
                await client.post(
                    action_url + "/dispatch", headers=case.headers, json={"expected_hash": "f" * 64}
                )
            ).status_code == 403
            dispatched = await client.post(
                action_url + "/dispatch",
                headers=case.headers,
                json={"expected_hash": probe.pending_hash},
            )
            assert dispatched.status_code == 200
            sent = PlanningDispatchRecord.model_validate_json(dispatched.content)
            await queue_row(database, sent.command)
            again = await client.post(
                action_url + "/dispatch",
                headers=case.headers,
                json={"expected_hash": probe.pending_hash},
            )
            assert again.status_code == 200
            assert PlanningDispatchRecord.model_validate_json(again.content) == sent.model_copy(
                update={"disposition": "existing"}
            )
            probe.candidate(case, review)
            # Retain the actual host pool even if startup fails after partial DBOS adoption.
            runtime = await capture_planning_worker_runtime(app)
            runtime = await start_planning_application_worker(app, database.system_url)
            observed = await result(sent.command.workflow_id)
            outcomes.append(observed)
            assert (
                observed.status == "historical_candidate" and observed.native_state == "succeeded"
            )
            assert observed.lease_released and not observed.resources_pending
            assert len(probe.posts) == probe.lookups == 1 and not app.runtime.pending_owners()
            candidate_url = action_url + "/candidate"
            candidate = await client.get(
                candidate_url,
                headers=case.headers,
                params={"expected_current_revision_id": str(base.plan_revision_id)},
            )
            assert candidate.status_code == 200
            value = PlanningCandidateReview.model_validate_json(candidate.content)
            assert (
                value.content == probe.content and value.historical and not value.company_completed
            )
            selected["expected_current_revision_id"] = str(base.plan_revision_id)
            proposal = await client.post(
                action_url + "/proposal", headers=case.headers, json=selected
            )
            assert proposal.status_code == 200
            revised = PlanRevision.model_validate_json(proposal.content)
            assert revised.revision == 2 and revised.payload.procedure == base.payload.procedure
            assert revised.payload.children[0] == base.payload.children[0]
            assert len(revised.payload.children) == 6
            approve_r2 = base_url + f"/management/plans/{revised.plan_revision_id}/approve"
            r2_decision = {
                "exact_hash": revised.sha256,
                "expected_current_revision_id": str(base.plan_revision_id),
            }
            assert (
                await client.post(approve_r2, headers=case.headers, json=r2_decision)
            ).status_code == 200
            r2_decision["expected_current_revision_id"] = str(revised.plan_revision_id)
            assert (
                await client.post(approve_r2, headers=case.headers, json=r2_decision)
            ).status_code == 200
            selected["expected_current_revision_id"] = str(revised.plan_revision_id)
            proposal_replay = await client.post(
                action_url + "/proposal", headers=case.headers, json=selected
            )
            assert proposal_replay.status_code == 200
            assert PlanRevision.model_validate_json(proposal_replay.content) == revised
            probe.unavailable = True
            case.credentials.unavailable = True
            replay = await execute_planning_segment(
                app.runtime,
                sent.command,
                workflow_id=sent.command.workflow_id,
                end_us=clock_us() + 30_000_000,
            )
            outcomes.append(replay)
            assert (
                replay.replayed
                and replay.status == "known_history"
                and replay.native_state == "succeeded"
            )
            assert not replay.resources_pending and len(probe.posts) == probe.lookups == 1
            await denied_builder(database, case.ready, case.engineer.identity, client, case.headers)
            assert len(probe.posts) == 1
            await revoke_document(database, case)
            assert (
                await client.get(
                    candidate_url,
                    headers=case.headers,
                    params={"expected_current_revision_id": str(revised.plan_revision_id)},
                )
            ).status_code == 403
            assert (
                await client.post(approve_r2, headers=case.headers, json=r2_decision)
            ).status_code == 403
            await conserved(database, case, recovered, action.action_id)
    finally:
        first_error = sys.exc_info()[0]
        try:
            with (root / "application-evidence.json").open("x") as stream:
                json.dump(
                    {
                        "database": DATABASE,
                        "started_utc": started.isoformat(),
                        "finished_utc": datetime.now(UTC).isoformat(),
                        "source_document_sha256": DOCUMENT_SHA256,
                        "source_document_commit": DOCUMENT_COMMIT,
                        "controlled_pending_interruption": probe.pending_hash,
                        "command": sent.command.model_dump(mode="json") if sent else None,
                        "outcomes": [row.model_dump(mode="json") for row in outcomes],
                        "mock_post_sha256s": probe.posts,
                        "revised_plan_sha256": revised.sha256 if revised else None,
                        "first_error_type": first_error.__name__ if first_error else None,
                        "limitations": [
                            "synthetic eligibility, not genuine quality",
                            "SDK MockTransport only",
                            "cold recomposition/in-process DBOS, not process restart",
                            "native builder denied; no patch/business completion",
                        ],
                    },
                    stream,
                    sort_keys=True,
                    indent=2,
                )
                stream.write("\n")
            (root / "application-evidence.json").chmod(0o600)
        finally:
            for graph in case.applications:
                await drain_planning_application(graph)
                assert not graph.lifecycle.pending_owners()
            if runtime is not None:
                await runtime.destroy()
                assert (
                    getattr(asyncio.get_running_loop(), "_default_executor", None)
                    is runtime.executor
                )
                assert getattr(runtime.executor, "_shutdown", None) is False
