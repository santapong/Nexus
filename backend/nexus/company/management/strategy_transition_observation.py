"""Pure transition consistency and retained windows, without native or owner authority."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.cycle_admission import validate_stockflow_cycle
from nexus.company.management.cycle_catalog_checks import validate_cycle_catalog
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.management.plan_admission_capture import CapturedPlanAdmission
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plan_registration import registration
from nexus.company.management.plans import PlanPayload
from nexus.company.management.report_input_contracts import native_author
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.strategy.acceptance import build_strategy_acceptance
from nexus.company.strategy.artifact_contracts import StrategyWriteParameters
from nexus.company.strategy.artifact_identity import strategy_reference
from nexus.company.strategy.check_output import prepare_strategy_check
from nexus.company.strategy.contracts import (
    STRATEGY_CHECK_CRITERIA,
    STRATEGY_CHECK_RECIPE,
    StrategyBrief,
    StrategyCandidateScope,
    StrategyCheckInput,
)
from nexus.company.strategy.current_proof_contracts import StrategyCurrentProof
from nexus.company.strategy.owner_selection import describe_strategy_selection
from nexus.company.strategy.publication_contracts import StrategyLoadedPublication
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.harness.canonical import action_hash


def _require(value: bool) -> None:
    if not value:
        raise ManagementDeniedError("Strategy transition description is unavailable")


def _fences(proof: StrategyCurrentProof) -> None:
    values = (
        proof.original.original_intent_fence,
        proof.author_original_fence,
        proof.author_current_fence,
        proof.verifier.original_intent_fence,
        proof.verifier_current_fence,
    )
    _require(
        all(type(value) is int and value > 0 for value in values)
        and proof.author_original_fence == proof.original.original_intent_fence
        and proof.author_original_fence <= proof.author_current_fence
        and proof.verifier.original_intent_fence <= proof.verifier_current_fence
    )


def _fingerprint(proof: StrategyCurrentProof) -> tuple[object, ...]:
    _fences(proof)
    return (
        proof.selection,
        proof.original,
        proof.acceptance,
        proof.brief,
        proof.verifier,
        proof.check_result,
        proof.author_original_fence,
        proof.author_current_fence,
        proof.verifier_current_fence,
    )


@dataclass(frozen=True)
class StrategyTransitionObservation:
    """Process-local observations from the actual orchestrator; no caller permission DTO."""

    admission: CapturedPlanAdmission
    proof: StrategyCurrentProof
    candidate: StrategyCandidateScope

    def require_time(self, now: datetime) -> None:
        """The actual caller supplies its last DB clock after every later await."""
        self.admission.window.require_time(now)
        self.proof.require_time(now)

    def require_same_proof(self, current: "StrategyTransitionObservation") -> None:
        """Retain original facts, allowing current pair plan/clocks to change at staged head2."""
        self.admission.window.require_same_scope(current.admission.window)
        _require(
            self.candidate == current.candidate
            and _fingerprint(self.proof) == _fingerprint(current.proof)
        )


def _original(proof: StrategyCurrentProof) -> StrategyLoadedPublication:
    quota = proof.original.prepared.original.snapshot.author_registration.quota
    AttemptQuota.model_validate({name: getattr(quota, name) for name in AttemptQuota.model_fields})
    loaded = StrategyLoadedPublication.model_validate(proof.original.model_dump(warnings=False))
    brief = StrategyBrief.model_validate_json(loaded.prepared.compiled.prepared.raw_bytes)
    _require(brief == proof.brief and loaded.prepared.brief == proof.selection.brief)
    pins = StrategyWriteParameters.model_validate_json(
        json.dumps(loaded.action.parameters, allow_nan=False)
    )
    _require(
        pins.selector.scope == loaded.prepared.original.snapshot.scope
        and pins.output_sha256 == loaded.prepared.brief.sha256
        and pins.input_snapshot_sha256 == loaded.prepared.compiled.prepared.input_snapshot_sha256
        and pins.input_manifest_sha256 == loaded.prepared.compiled.prepared.input_manifest_sha256
    )
    _fences(proof)
    return loaded


def _current_pair(
    payload: PlanPayload, catalog: PlanAdmissionCatalog, proof: StrategyCurrentProof
) -> None:
    # Preserve original digests; equal Decimal values may have different scales.
    configured = catalog.cycle_admission
    assert configured is not None
    original = proof.original.prepared.original.snapshot
    _require(
        original.scope.company_id == payload.company_id
        and original.scope.goal == payload.goal
        and original.scope.producing_plan.plan_id == payload.plan.plan_id
        and original.scope.producing_plan.revision == 1
        and original.scope.author == configured.slots[0].child.binding
        and original.scope.verifier == configured.slots[1].child.binding
        and original.policy.goal_id == payload.goal.goal_id
    )
    for protected in (proof.initial, proof.current):
        _require(canonical_sha256(protected.catalog) == canonical_sha256(catalog))
        pair = protected.pair
        selected = validate_stockflow_cycle(configured, catalog.models, pair.plan)
        _require(
            selected is not None
            and selected.stage in {"strategy", "full"}
            and pair.plan.procedure == payload.procedure
            and pair.plan.goal == payload.goal
            and pair.plan.plan.plan_id == payload.plan.plan_id
        )
        for index, (work, child, fence) in enumerate(
            (
                (pair.author, pair.author_child, proof.author_current_fence),
                (pair.verifier, pair.verifier_child, proof.verifier_current_fence),
            )
        ):
            slot = configured.slots[index]
            actual, saved = native_author(work)
            _require(
                child == slot.child
                and actual == child.binding
                and saved == registration(slot.child.binding, slot.work, slot.child.quota)
                and work.parent_task_id == payload.procedure.binding.task_id
                and work.state not in {"blocked", "outcome_unknown"}
                and type(work.fence) is int
                and work.fence == fence
            )
            if index == 0:
                _require(
                    saved == original.author_registration
                    and work.registration_hash == original.scope.author_registration_sha256
                )


def _check_result(catalog: PlanAdmissionCatalog, proof: StrategyCurrentProof) -> None:
    # Recompute supplied data only; the reader proves actual C graph/READ/receipt authority.
    loaded, target = proof.original, proof.acceptance.target
    original = loaded.prepared.original.snapshot
    action, receipt = loaded.action, loaded.receipt
    _require(
        (target.author, target.verifier) == (original.scope.author, original.scope.verifier)
        and target.company_id == original.company_id
        and target.action_id == action.action_id == loaded.prepared.action_id
        and target.proposal_sha256 == receipt.proposal_hash == action_hash(action)
        and target.receipt_id == receipt.receipt_id
        and target.receipt_sha256 == canonical_sha256(receipt)
        and target.work_snapshot_sha256 == original.scope.author_registration_sha256
        and target.artifacts == (loaded.prepared.brief,)
        and target.check_recipe == STRATEGY_CHECK_RECIPE
        and target.criterion_ids == STRATEGY_CHECK_CRITERIA
    )
    refs = (
        *original.inputs.artifacts,
        loaded.prepared.compiled.original_bundle.artifact,
        loaded.prepared.brief,
    )
    inputs = GeneratedArtifactInputs(
        **original.inputs.model_dump(exclude={"artifacts", "required_resource_ids"}),
        artifacts=tuple(sorted(refs, key=lambda row: row.artifact_revision_id)),
        required_resource_ids=tuple(
            sorted(
                set(original.inputs.required_resource_ids)
                | {loaded.prepared.compiled.original_bundle.resource.resource_id}
            )
        ),
    )
    command = StrategyCheckInput(
        company_id=target.company_id,
        target=target,
        output=loaded.prepared.brief,
        output_utf8=loaded.prepared.compiled.prepared.raw_bytes,
        snapshot=original,
    )
    prepared = prepare_strategy_check(
        command, inputs, loaded.prepared.compiled.prepared.data_classification
    )
    facts = proof.verifier
    configured = catalog.cycle_admission
    assert configured is not None
    for proposal, slot in ((action, configured.slots[0]), (facts.action, configured.slots[1])):
        _require(
            (proposal.company_id, proposal.actor_id, proposal.task_id, proposal.trace_id)
            == (
                configured.company_id,
                slot.child.binding.actor_id,
                slot.child.binding.task_id,
                slot.child.binding.trace_id,
            )
            and (proposal.tool, proposal.tool_version, proposal.resource)
            == (slot.tool.tool, slot.tool.tool_version, slot.tool.resource)
        )
    _require(
        configured.company_id == proof.selection.company_id
        and strategy_reference(prepared, facts.action.action_id) == facts.protected_result
        and proof.check_result.model_dump_json().encode() == prepared.raw_bytes
        and hashlib.sha256(prepared.raw_bytes).hexdigest() == facts.parameters.output_sha256
        and build_strategy_acceptance(
            command, inputs, facts, prepared.raw_bytes, proof.acceptance.recorded_at
        )
        == proof.acceptance
    )


def validate_transition_proof(
    payload: PlanPayload,
    catalog: PlanAdmissionCatalog,
    proof: StrategyCurrentProof,
) -> StrategyCandidateScope:
    """Describe one exact change; the concrete reader proves actual policy and authority."""
    configured = validate_cycle_catalog(catalog.cycle_admission, catalog)
    selected = validate_stockflow_cycle(configured, catalog.models, payload)
    _require(
        configured is not None
        and selected is not None
        and selected.stage == "full"
        and payload.strategy_selection is not None
    )
    assert configured is not None
    loaded = _original(proof)
    _require(payload.strategy_selection == proof.selection)
    _current_pair(payload, catalog, proof)
    _check_result(catalog, proof)
    snapshot, policy, brief = (
        loaded.prepared.original.snapshot,
        loaded.prepared.original.policy,
        proof.brief,
    )
    _require(
        brief.repository == snapshot.policy.repository
        and brief.source_manifest_sha256 == snapshot.policy.source_manifest_sha256
        and policy.scope_sha256 == canonical_sha256(snapshot.scope)
        and policy.candidate_policy_sha256 == canonical_sha256(snapshot.policy)
        and tuple(row.scope for row in brief.candidates) == snapshot.policy.candidates
        and tuple(row.scope for row in policy.candidates) == snapshot.policy.candidates
    )
    matches = tuple(
        row
        for row in snapshot.policy.candidates
        if row.candidate_id == proof.selection.candidate_id
    )
    _require(len(matches) == 1)
    candidate = StrategyCandidateScope.model_validate(matches[0].model_dump(warnings=False))
    _require(
        candidate.kind == "change"
        and candidate.tool == configured.slots[2].tool
        and canonical_sha256(candidate) == proof.selection.candidate_scope_sha256
        and describe_strategy_selection(brief, proof.acceptance, candidate.candidate_id)
        == proof.selection
    )
    return candidate
