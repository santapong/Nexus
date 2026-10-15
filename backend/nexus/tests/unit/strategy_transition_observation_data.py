"""Coherent SUPPLIED transition descriptions only; no native proof reader, DB or authority."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid5

import jwt
from pydantic import JsonValue, SecretStr

from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.cycle_admission_contracts import StockFlowCycleAdmission
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.plan_admission_capture import CapturedPlanAdmission
from nexus.company.management.plan_admission_window import PlanAdmissionWindow, PlanGrantWindow
from nexus.company.management.plan_registration import registration
from nexus.company.management.plans import PlanPayload
from nexus.company.management.strategy_transition_observation import StrategyTransitionObservation
from nexus.company.notifications.worker_identity import _verify
from nexus.company.strategy.acceptance import build_strategy_acceptance
from nexus.company.strategy.artifact_contracts import (
    StrategyBriefSelector,
    StrategyCheckParameters,
    StrategyWriteParameters,
)
from nexus.company.strategy.artifact_identity import strategy_reference
from nexus.company.strategy.check_output import prepare_strategy_check
from nexus.company.strategy.contracts import (
    STRATEGY_CHECK_CRITERIA,
    STRATEGY_CHECK_RECIPE,
    StrategyBrief,
    StrategyCheckInput,
)
from nexus.company.strategy.current_proof_contracts import StrategyCurrentProof
from nexus.company.strategy.owner_selection import describe_strategy_selection
from nexus.company.strategy.pair_reader import StrategyNativePair
from nexus.company.strategy.publication_contracts import StrategyLoadedPublication
from nexus.company.strategy.publication_identity import prepare_strategy_publication
from nexus.company.strategy.publication_protection import StrategyReadProtection
from nexus.company.strategy.source_inputs import StrategySourceProtection
from nexus.company.strategy.verifier_facts import StrategyVerifierReceipt
from nexus.core.llm.company_registry import EvaluationEvidence, ModelHealth, ModelRegistry, Profile
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import registration_digest
from nexus.harness.canonical import action_hash
from nexus.tests.unit.cycle_admission_fixture import declared
from nexus.tests.unit.cycle_catalog_fixture import cycle_catalog
from nexus.tests.unit.strategy_producer_fixture import producer_case
from nexus.tests.unit.test_company_model_registry import model


@dataclass(frozen=True)
class TransitionData:
    observation: StrategyTransitionObservation
    payload: PlanPayload
    now: datetime


def _work(admission: StockFlowCycleAdmission, index: int) -> ExecutionWork:
    slot = admission.slots[index]
    bound, quota = slot.child.binding, slot.child.quota
    saved = registration(bound, slot.work, quota)
    row = ExecutionWork(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        workspace_id=bound.workspace_id,
        actor_id=bound.actor_id,
        run_id=bound.run_id,
        parent_task_id=admission.procedure.binding.task_id,
        workflow_name=bound.workflow_name,
        workflow_version=bound.workflow_version,
        model_profile=bound.model_profile,
        model_registry_version=bound.model_registry_version,
        registration_json=saved.model_dump_json(),
        registration_hash=registration_digest(saved),
        state="verifying",
        fence=2,
        segment_number=1,
        segment_id=uuid5(bound.run_id, "nexus-execution-segment-v1:1"),
        worker_id=None,
        lease_until=None,
        lease_mode=None,
        lease_principal_id=None,
        waiting_action_id=None,
    )
    for kind in ("model_requests", "tool_attempts", "rework_rounds", "plan_revisions"):
        setattr(row, kind + "_limit", getattr(quota, kind))
        setattr(row, kind + "_used", int(kind == "tool_attempts"))
        setattr(row, kind + "_delegated", 0)
    return row


def transition_data(head: int = 1) -> TransitionData:
    """Build typed descriptions with mechanical eligibility, without provider-health proof."""
    # This >50-line fixture keeps original body, role registrations and proof fingerprints coherent.
    now = datetime.now(UTC).replace(microsecond=0)
    profiles: tuple[Profile, ...] = ("reasoning", "routine", "verification")
    eligibility = model(
        "synthetic-transition",
        price=None,
        health=ModelHealth(
            status="healthy",
            checked_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(hours=1),
        ),
        evaluations=tuple(
            EvaluationEvidence(
                profile=p,
                suite_version="synthetic",
                artifact_reference="fixture:no-live-health",
                score=Decimal(1),
                conformance_passed=True,
                evaluated_at=now - timedelta(seconds=1),
                expires_at=now + timedelta(hours=1),
            )
            for p in profiles
        ),
    )
    registry = ModelRegistry(
        company_id=UUID(int=1),
        revision="cycle-models-v1",
        pricebook_version="p1",
        models=(eligibility,),
    )
    catalog_data = cycle_catalog(registry)
    admission = catalog_data.admission
    slots = list(admission.slots)
    for index in (0, 1):
        slots[index] = slots[index].model_copy(
            update={
                "work": slots[index].work.model_copy(update={"acceptance": STRATEGY_CHECK_CRITERIA})
            }
        )
    slots[-1] = slots[-1].model_copy(
        update={
            "child": slots[-1].child.model_copy(
                update={
                    "binding": slots[-1].child.binding.model_copy(update={"actor_id": UUID(int=99)})
                }
            )
        }
    )
    admission = admission.model_copy(
        update={
            "slots": tuple(slots),
            "procedure": admission.procedure.model_copy(
                update={
                    "binding": admission.procedure.binding.model_copy(
                        update={"actor_id": UUID(int=99)}
                    )
                }
            ),
        }
    )
    catalog = catalog_data.catalog.model_copy(update={"cycle_admission": admission})
    first = declared(admission, 1)
    full = declared(admission, 2)
    snapshot, policy = producer_case()
    author = registration(slots[0].child.binding, slots[0].work, slots[0].child.quota)
    scope = snapshot.scope.model_copy(
        update={
            "goal": admission.goal,
            "author": slots[0].child.binding,
            "verifier": slots[1].child.binding,
            "author_registration_sha256": registration_digest(author),
            "producing_plan": PlanRevisionRef(
                company_id=admission.company_id,
                plan_id=admission.plan_id,
                revision=1,
                sha256=canonical_sha256(first),
                plan_revision_id=uuid5(admission.plan_id, "plan:1:" + canonical_sha256(first)),
            ),
        }
    )
    candidate_policy = snapshot.policy.model_copy(
        update={
            "goal_id": admission.goal.goal_id,
            "candidates": (
                snapshot.policy.candidates[0].model_copy(update={"tool": slots[2].tool}),
                snapshot.policy.candidates[1],
            ),
        }
    )
    snapshot = snapshot.model_copy(
        update={"scope": scope, "author_registration": author, "policy": candidate_policy}
    )
    policy = policy.model_copy(
        update={
            "scope_sha256": canonical_sha256(scope),
            "candidate_policy_sha256": canonical_sha256(candidate_policy),
            "candidates": tuple(
                row.model_copy(update={"scope": candidate_policy.candidates[i]})
                for i, row in enumerate(policy.candidates)
            ),
        }
    )
    target_resource = catalog.resources[0].resource
    prepared = prepare_strategy_publication(snapshot, policy, UUID(int=1001), target_resource)
    params = StrategyWriteParameters(
        selector=StrategyBriefSelector(scope=scope),
        output_sha256=prepared.brief.sha256,
        input_snapshot_sha256=prepared.compiled.prepared.input_snapshot_sha256,
        input_manifest_sha256=prepared.compiled.prepared.input_manifest_sha256,
    )

    def action(index: int, identifier: int, parameters: dict[str, JsonValue]) -> ActionProposal:
        slot = slots[index]
        b = slot.child.binding
        return ActionProposal(
            company_id=b.company_id,
            action_id=UUID(int=identifier),
            actor_id=b.actor_id,
            task_id=b.task_id,
            trace_id=b.trace_id,
            revision=1,
            tool=slot.tool.tool,
            tool_version=slot.tool.tool_version,
            resource=slot.tool.resource,
            parameters=parameters,
            policy_version="p1",
            price_version="p1",
            estimated_cost_usd=Decimal(".01"),
        )

    saction = action(0, 1001, params.model_dump(mode="json"))

    def receipt(
        proposal: ActionProposal, identifier: int, ref: ArtifactRevisionRef
    ) -> ActionReceipt:
        return ActionReceipt(
            company_id=proposal.company_id,
            receipt_id=UUID(int=identifier),
            action_id=proposal.action_id,
            task_id=proposal.task_id,
            trace_id=proposal.trace_id,
            proposal_hash=action_hash(proposal),
            outcome="succeeded",
            recorded_at=now,
            artifacts=(
                ArtifactRef(
                    company_id=proposal.company_id,
                    artifact_id=ref.artifact_id,
                    reference="supplied descriptive fixture",
                    revision=ref.revision,
                    sha256=ref.sha256,
                ),
            ),
        )

    sr = receipt(saction, 1002, prepared.brief)
    from nexus.company.management.acceptance import VerificationSpec

    target = VerificationSpec(
        company_id=admission.company_id,
        author=scope.author,
        verifier=scope.verifier,
        action_id=saction.action_id,
        proposal_sha256=action_hash(saction),
        receipt_id=sr.receipt_id,
        receipt_sha256=canonical_sha256(sr),
        work_snapshot_sha256=scope.author_registration_sha256,
        criterion_ids=STRATEGY_CHECK_CRITERIA,
        artifacts=(prepared.brief,),
        check_recipe=STRATEGY_CHECK_RECIPE,
    )
    command = StrategyCheckInput(
        company_id=admission.company_id,
        target=target,
        output=prepared.brief,
        output_utf8=prepared.compiled.prepared.raw_bytes,
        snapshot=snapshot,
    )
    refs = (*snapshot.inputs.artifacts, prepared.compiled.original_bundle.artifact, prepared.brief)
    inputs = GeneratedArtifactInputs(
        **snapshot.inputs.model_dump(exclude={"artifacts", "required_resource_ids"}),
        artifacts=tuple(sorted(refs, key=lambda r: r.artifact_revision_id)),
        required_resource_ids=tuple(
            sorted(set(snapshot.inputs.required_resource_ids) | {target_resource.resource_id})
        ),
    )
    check = prepare_strategy_check(command, inputs, "internal")
    pins = StrategyCheckParameters(
        author_action_id=saction.action_id,
        verification_target_sha256=canonical_sha256(target),
        output_sha256=check.output_sha256,
        input_snapshot_sha256=check.input_snapshot_sha256,
    )
    svaction = action(1, 1003, pins.model_dump(mode="json"))
    cref = strategy_reference(check, svaction.action_id)
    svr = receipt(svaction, 1004, cref)
    facts = StrategyVerifierReceipt(svaction, svr, 1, cref, pins)
    accepted = build_strategy_acceptance(command, inputs, facts, check.raw_bytes, now)
    brief = StrategyBrief.model_validate_json(prepared.compiled.prepared.raw_bytes)
    selected = describe_strategy_selection(brief, accepted, brief.candidates[0].scope.candidate_id)
    full = full.model_copy(update={"strategy_selection": selected})
    key = SecretStr(
        "synthetic-transition-observation-test-key-at-least64-characters-no-live-secret"
    )
    credential = _verify(
        SecretStr(
            jwt.encode(
                {
                    "sub": str(admission.procedure.binding.actor_id),
                    "workspace_id": str(admission.procedure.binding.workspace_id),
                    "iat": int(now.timestamp()) - 1,
                    "exp": int(now.timestamp()) + 300,
                },
                key.get_secret_value(),
                algorithm="HS256",
            )
        ),
        key,
    )
    pair = StrategyNativePair(
        first if head == 1 else full,
        _work(admission, 0),
        _work(admission, 1),
        slots[0].child,
        slots[1].child,
    )
    grant = ResourceGeneration(
        company_id=admission.company_id,
        resource_id=snapshot.inputs.required_resource_ids[0],
        generation=1,
        expires_at=now + timedelta(seconds=60),
    )
    read = StrategyReadProtection(
        StrategySourceProtection((grant,), (), credential), (grant,), pair, catalog
    )
    from nexus.company.strategy.contracts import StrategyCheckResult

    proof = StrategyCurrentProof(
        selected,
        StrategyLoadedPublication(
            prepared=prepared, action=saction, receipt=sr, original_intent_fence=1
        ),
        accepted,
        brief,
        facts,
        StrategyCheckResult.model_validate_json(check.raw_bytes),
        1,
        2,
        2,
        read,
        read,
        now,
    )
    window = PlanAdmissionWindow(
        admission.company_id,
        credential.identity.principal_id,
        credential.identity.workspace_id,
        canonical_sha256(full),
        canonical_sha256(catalog),
        "p1",
        "p1",
        now,
        (),
        (
            PlanGrantWindow(
                grant.resource_id, credential.identity.principal_id, 1, 1, grant.expires_at
            ),
        ),
        (),
        None,
        None,
        credential,
    )
    observation = StrategyTransitionObservation(
        CapturedPlanAdmission({}, window), proof, candidate_policy.candidates[0]
    )
    return TransitionData(observation, full, now)
