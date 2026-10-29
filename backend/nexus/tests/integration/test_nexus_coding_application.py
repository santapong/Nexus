"""Opt-in HTTP/PG/DBOS L→C protocol acceptance; never vendor or builder qualification.

This source is inert until Root releases the exact fresh namespace. The single
ordered scenario preserves original windows, rows, native counters and failures.
Synthetic eligibility/prices and SDK MockTransport are explicitly test inputs.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from litestar.testing import AsyncTestClient

from nexus.builder.contained_query import clock_us
from nexus.company.management.coding_publication_contracts import PublishedCodingPatch
from nexus.company.management.cycle_cost_contracts import CycleCostSnapshot
from nexus.company.management.lifecycle import PlanRevision
from nexus.execution.coding_application import coding_app
from nexus.execution.coding_application_runtime import drain_coding_application
from nexus.execution.coding_dispatch import CodingDispatchRecord
from nexus.execution.coding_lifecycle_contracts import CodingCandidateReview
from nexus.execution.coding_owner_reads import CodingInputReview
from nexus.execution.planning_dispatch import PlanningDispatchRecord
from nexus.execution.planning_lifecycle_contracts import PlanningCandidateReview
from nexus.execution.planning_owner_reads import PlanningInputReview
from nexus.execution.planning_preparation import PreparedPlanningAction
from nexus.harness.model_authorizer_contracts import model_action_parameters
from nexus.tests.integration.nexus_coding_application_fixture import (
    Database,
    decision,
    open_database,
    prepare_case,
    recover_coding,
    revoke_source,
    safe_report,
)
from nexus.tests.integration.nexus_coding_application_sources import (
    PYTEST_BASETEMP,
    publish_candidate,
)
from nexus.tests.integration.nexus_coding_application_transport import (
    coding_output,
    planning_output,
)
from nexus.tests.integration.nexus_coding_application_worker import (
    run_worker,
    settle_workers,
    wait_before,
    worker_bounds,
)


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    """No DB connection, migration or child process is made during collection."""
    async for value in open_database():
        yield value


async def test_real_owner_l_then_c_publication_cost_and_conservation(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Cohesion exception: one irreversible scenario is intentionally not split/reset.

    Its negative checks precede irreversible transitions; every failure stops the
    wave and leaves the actual database and complete private files for Root audit.
    Root's counters are its own native counters, not the L+C family sum.
    """
    started = datetime.now(UTC)
    observation_end_us = clock_us() + 600_000_000
    # This body check cannot protect a wrong CLI: Root validates BEFORE pytest starts.
    assert Path(request.config.getoption("basetemp")).resolve() == PYTEST_BASETEMP
    assert tmp_path.resolve().is_relative_to(PYTEST_BASETEMP)
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    case = await prepare_case(database, root, monkeypatch, observation_end_us=observation_end_us)
    app = case.compose(database)
    base = f"/api/v2/companies/{case.config.catalog.company_id}"
    planning = base + f"/planning/goals/{case.config.goal.goal_id}"
    selected: dict[str, object] = {
        "goal": case.config.goal.model_dump(mode="json"),
        "expected_current_revision_id": None,
    }
    plans: list[PlanRevision] = []
    workers = []
    publication: PublishedCodingPatch | None = None
    costs: CycleCostSnapshot | None = None
    try:
        async with AsyncTestClient(coding_app(app), raise_server_exceptions=False) as client:
            assert (await client.get(planning + "/status")).status_code == 401
            assert (
                await client.get(planning + "/status", headers=case.member_headers)
            ).status_code == 403
            made = await client.post(planning + "/bootstrap", headers=case.headers, json=selected)
            assert made.status_code == 200
            r1 = PlanRevision.model_validate_json(made.content)
            plans.append(r1)
            assert r1.payload == case.config.admission.payload("planning")
            assert len(r1.payload.children) == 1
            assert r1.payload.procedure.allocation_usd == 1
            selected["expected_current_revision_id"] = str(r1.plan_revision_id)
            assert (
                await client.post(planning + "/prepare", headers=case.headers, json=selected)
            ).status_code == 403
            await decision(client, case, r1)
            prepared_http = await client.post(
                planning + "/prepare", headers=case.headers, json=selected
            )
            assert prepared_http.status_code == 200
            prepared_l = PreparedPlanningAction.model_validate_json(prepared_http.content)
            assert prepared_l.work.state == "awaiting_approval"
            assert prepared_l.work.worker_id is None
            assert prepared_l.work.counters.model_requests == 0
            lurl = base + f"/planning/actions/{prepared_l.action.proposal.action_id}"
            viewed_l = await client.get(lurl + "/input", headers=case.headers)
            assert viewed_l.status_code == 200
            review_l = PlanningInputReview.model_validate_json(viewed_l.content)
            assert review_l.prepared.input_estimate is not None
            assert review_l.prepared.input_estimate.whole_request is not None
            assert review_l.maximum_reservation_usd == prepared_l.quote.amount_usd
            assert review_l.prepared.context.manifest.inclusions
            assert case.source.document.sha256 in {
                row.handle.record.artifact.sha256
                for row in review_l.prepared.context.manifest.inclusions
            }
            generic_l = await client.get(
                base + f"/management/actions/{prepared_l.action.proposal.action_id}/review",
                headers=case.headers,
            )
            assert generic_l.status_code == 200
            assert generic_l.json()["availability"] == "available"
            await case.approve_action(client, prepared_l.action)
            l_bounds = worker_bounds(case, "planner", review_l.prepared.context.manifest)
            sent_l_http = await client.post(
                lurl + "/dispatch",
                headers=case.headers,
                json={"expected_hash": prepared_l.action.proposal_hash},
            )
            assert sent_l_http.status_code == 200
            sent_l = PlanningDispatchRecord.model_validate_json(sent_l_http.content)
            await database.require_queue(sent_l.command, "planner")
            assert review_l.prepared.request.output_schema is not None
            lworker = await run_worker(
                case,
                database,
                "planner",
                sent_l.command,
                planning_output(case.config.admission, review_l),
                root / "planner-child",
                expected_schema=review_l.prepared.request.output_schema,
                bounds=l_bounds,
            )
            workers.append(lworker)
            assert lworker.result.status == "historical_candidate"
            assert lworker.result.native_state == "succeeded"
            assert lworker.result.lease_released and not lworker.result.resources_pending
            assert len(lworker.post_sha256s) == lworker.endpoint_lookups == 1
            candidate_l_http = await client.get(
                lurl + "/candidate",
                headers=case.headers,
                params={"expected_current_revision_id": str(r1.plan_revision_id)},
            )
            assert candidate_l_http.status_code == 200
            candidate_l = PlanningCandidateReview.model_validate_json(candidate_l_http.content)
            assert candidate_l.historical and not candidate_l.company_completed
            formal = await client.post(lurl + "/proposal", headers=case.headers, json=selected)
            assert formal.status_code == 200
            r2 = PlanRevision.model_validate_json(formal.content)
            plans.append(r2)
            assert r2.revision == 2 and len(r2.payload.children) == 10
            assert r2.payload.procedure == r1.payload.procedure
            assert r2.payload.children[0] == r1.payload.children[0]
            assert r2.payload.planning_origin == candidate_l.origin
            assert r2.payload.coding_admission_sha256 == r1.payload.coding_admission_sha256
            await decision(client, case, r2, previous=r1)
            selected["expected_current_revision_id"] = str(r2.plan_revision_id)
            # Exactly one controlled crash after actual C pending, before native wait.
            # The cold graph and public recovery below consume the SAME packet/hash.
            prepared_c, app = await recover_coding(database, case, app, client, selected, root)
        async with AsyncTestClient(coding_app(app), raise_server_exceptions=False) as client:
            curl = base + f"/coding/actions/{prepared_c.action.proposal.action_id}"
            assert (await client.get(curl + "/input")).status_code == 401
            assert (
                await client.get(curl + "/input", headers=case.member_headers)
            ).status_code == 403
            viewed_c = await client.get(curl + "/input", headers=case.headers)
            assert viewed_c.status_code == 200
            review_c = CodingInputReview.model_validate_json(viewed_c.content)
            assert review_c.proposal == prepared_c.action.proposal
            assert review_c.proposal_sha256 == prepared_c.action.proposal_hash
            assert review_c.reference == prepared_c.reference
            assert review_c.prepared.input_estimate.whole_request is not None
            assert review_c.maximum_reservation_usd == prepared_c.quote.amount_usd
            assert review_c.prepared.binding.source == case.source.source
            assert review_c.prepared.sources == case.config.code_sources
            assert len(review_c.proposal.parameters) == 9
            assert review_c.proposal.parameters == model_action_parameters(
                review_c.prepared.request, case.config.recipe
            )
            assert review_c.reference.condition in review_c.proposal.preconditions
            assert (
                len({review_c.header_sha256, review_c.request_sha256, review_c.proposal_sha256})
                == 3
            )
            generic_c = await client.get(
                base + f"/management/actions/{prepared_c.action.proposal.action_id}/review",
                headers=case.headers,
            )
            assert generic_c.status_code == 200
            assert generic_c.json()["availability"] == "available"
            assert not review_c.execution_permitted and not review_c.company_completed
            await case.approve_action(client, prepared_c.action)
            assert (
                await client.post(
                    curl + "/dispatch", headers=case.headers, json={"expected_hash": "f" * 64}
                )
            ).status_code == 403
            c_bounds = worker_bounds(case, "coder", review_c.prepared.context.manifest)
            sent_c_http = await client.post(
                curl + "/dispatch",
                headers=case.headers,
                json={"expected_hash": prepared_c.action.proposal_hash},
            )
            assert sent_c_http.status_code == 200
            sent_c = CodingDispatchRecord.model_validate_json(sent_c_http.content)
            await database.require_queue(sent_c.command, "coder")
            replay_dispatch = await client.post(
                curl + "/dispatch",
                headers=case.headers,
                json={"expected_hash": prepared_c.action.proposal_hash},
            )
            assert replay_dispatch.status_code == 200
            assert CodingDispatchRecord.model_validate_json(replay_dispatch.content) == (
                sent_c.model_copy(update={"disposition": "existing"})
            )
            assert review_c.prepared.request.output_schema is not None
            cworker = await run_worker(
                case,
                database,
                "coder",
                sent_c.command,
                coding_output(review_c, case.source_original),
                root / "coder-child",
                expected_schema=review_c.prepared.request.output_schema,
                bounds=c_bounds,
            )
            workers.append(cworker)
            assert cworker.pid != lworker.pid
            assert cworker.result.status == "historical_candidate"
            assert cworker.result.native_state == "succeeded"
            assert cworker.result.lease_released and not cworker.result.resources_pending
            assert len(cworker.post_sha256s) == cworker.endpoint_lookups == 1
            candidate_c_http = await client.get(
                curl + "/candidate",
                headers=case.headers,
                params={"expected_current_revision_id": str(r2.plan_revision_id)},
            )
            assert candidate_c_http.status_code == 200
            candidate_c = CodingCandidateReview.model_validate_json(candidate_c_http.content)
            assert candidate_c.historical and not candidate_c.company_completed
            assert candidate_c.request_sha256 == review_c.request_sha256
            publication = await publish_candidate(case, app, prepared_c, r2)
            assert not publication.company_completed
            assert (
                publication.patch_sha256
                == hashlib.sha256(candidate_c.content.patch.encode()).hexdigest()
            )
            await case.require_metadata_replays(app, sent_l.command, sent_c.command)
            cost_http = await client.get(base + "/management/cycle-costs", headers=case.headers)
            assert cost_http.status_code == 200
            costs = CycleCostSnapshot.model_validate_json(cost_http.content)
            assert costs.profile_bound and costs.complete_membership and not costs.blockers
            assert len(costs.expected_task_ids) == len(costs.observed_task_ids) == 11
            assert len(costs.unissued_task_ids) == 9
            charged = [row for row in costs.charges if row.attempt_kind == "model_requests"]
            assert len(charged) == 2 and all(row.confirmation == "known" for row in charged)
            assert costs.totals.held_usd == 0
            assert costs.totals.actual_total_usd == sum(
                row.ledger_actual_usd for row in charged if row.ledger_actual_usd is not None
            )
            assert not costs.company_completed
            before_spent = costs.totals.known_spent_usd
            await revoke_source(database, case)
            assert (await client.get(curl + "/input", headers=case.headers)).status_code == 403
            assert (
                await client.get(
                    curl + "/candidate",
                    headers=case.headers,
                    params={"expected_current_revision_id": str(r2.plan_revision_id)},
                )
            ).status_code == 403
            with pytest.raises(ValueError):
                await publish_candidate(case, app, prepared_c, r2)
            denied_cost = await client.get(base + "/management/cycle-costs", headers=case.headers)
            assert denied_cost.status_code == 200
            after = CycleCostSnapshot.model_validate_json(denied_cost.content)
            assert after.totals.actual_total_usd is None
            assert after.totals.known_spent_usd == before_spent
            assert after.totals.unconfirmed_action_ids
    finally:
        error = sys.exc_info()[0]
        database.first_error = database.first_error or sys.exc_info()[1]
        cleanup_error: BaseException | None = None
        for graph in case.applications:
            graph.planning.lifecycle.request_stop()
            graph.lifecycle.request_stop()
        for publisher in case.publishers:
            publisher.request_stop()

        async def retirement() -> None:
            for graph in case.applications:
                await drain_coding_application(graph)
            for publisher in case.publishers:
                while publisher.pending_owners():
                    await asyncio.sleep(0.05)

        owner = asyncio.create_task(retirement())
        case.retirement_owners.append(cast(asyncio.Task[object], owner))
        database.retirement_owners.append(cast(asyncio.Task[object], owner))
        try:
            try:
                await settle_workers(case)
            except BaseException as stopped:
                cleanup_error = stopped
            try:
                await wait_before(owner, case.observation_end_us)
            except BaseException as stopped:
                cleanup_error = cleanup_error or stopped
            database.first_error = database.first_error or cleanup_error
            if cleanup_error is not None and error is None:
                raise cleanup_error
            assert all(row.returncode == 0 for row in workers)
        finally:
            safe_report(
                root,
                started,
                error or sys.exc_info()[0],
                plans,
                workers,
                publication,
                costs,
                child_facts=tuple(row.facts() for row in case.children),
                retirement_pending=sum(
                    not row.done() or row.cancelled() for row in case.retirement_owners
                ),
            )
