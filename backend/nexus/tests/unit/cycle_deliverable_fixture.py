"""Wholly supplied-data fixture; no SQL, actual engineering run or work acceptance occurs."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from nexus.builder.engineering_checker import check_engineering_change
from nexus.builder.result_store import BuilderResultStore
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.sources import ArtifactRevisionRef, EvidenceRef
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.work import WorkItem
from nexus.company.cycle_artifacts.check_contracts import CycleArtifactCheckInput
from nexus.company.cycle_artifacts.citations import quote_sources
from nexus.company.cycle_artifacts.common import CycleKind, criteria_for, digest
from nexus.company.cycle_artifacts.contracts import CycleArtifactBasis
from nexus.company.cycle_artifacts.engineering import (
    EngineeringEvidence,
    compare_engineering_evidence,
)
from nexus.company.cycle_artifacts.production import (
    PreparedCycleDeliverable,
    prepare_presentation,
    prepare_support,
)
from nexus.company.management.acceptance import (
    ProtectedCheckProof,
    VerificationSpec,
    WorkAcceptance,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import CitationCheckSource
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.plans import RunBinding
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionRegistration
from nexus.execution.runtime_support import registration_digest
from nexus.tests.engineering_check_support import check_input
from nexus.tests.unit.strategy_brief_fixture import strategy_case


def engineering_evidence() -> EngineeringEvidence:
    """Keep complete synthetic summary/receipt/proof identity together in this >50-line fixture."""
    # These supplied summary/receipt/proof links form one synthetic case, not native observations.
    value = check_input()
    outputs, raws, receipts = [], [], []
    for result, ref, receipt in (
        (value.author, value.author_output, value.author_receipt),
        (value.verifier, value.verifier_output, value.verifier_receipt),
    ):
        raw = json.dumps(
            {
                "result_sha256": BuilderResultStore.digest(result),
                "spec": result.spec.model_dump(mode="json"),
                "proposal_sha256": result.proposal_sha256,
                "intent_fence": result.intent_fence,
                "outcome": result.outcome,
                "commands": [r.model_dump(mode="json") for r in result.commands],
                "artifacts": [r.metadata.model_dump(mode="json") for r in result.artifacts],
                "logs": [r.metadata.model_dump(mode="json") for r in result.logs],
                "limitations": result.limitations,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        changed = ref.model_copy(update={"sha256": digest(raw), "byte_length": len(raw)})
        outputs.append(changed)
        raws.append(raw)
        receipts.append(
            receipt.model_copy(
                update={
                    "artifacts": (
                        ArtifactRef(
                            company_id=changed.company_id,
                            artifact_id=changed.artifact_id,
                            revision=changed.revision,
                            sha256=changed.sha256,
                            reference="synthetic-protected-summary",
                        ),
                    )
                }
            )
        )
    target = value.target.model_copy(
        update={
            "artifacts": (outputs[0],),
            "receipt_id": receipts[0].receipt_id,
            "receipt_sha256": canonical_sha256(receipts[0]),
        }
    )
    value = value.model_copy(
        update={
            "target": target,
            "author_output": outputs[0],
            "verifier_output": outputs[1],
            "author_receipt": receipts[0],
            "verifier_receipt": receipts[1],
        }
    )
    proof = check_engineering_change(value)
    assert proof.verdict == "pass"
    raw_check = proof.model_dump_json().encode()
    check = ArtifactRevisionRef(
        company_id=value.company_id,
        artifact_id=uuid4(),
        artifact_revision_id=uuid4(),
        revision="synthetic-engineering-check",
        sha256=digest(raw_check),
        byte_length=len(raw_check),
    )
    acceptance = WorkAcceptance(
        company_id=value.company_id,
        acceptance_id=uuid4(),
        target=target,
        verdict="pass",
        limitations=proof.limitations,
        recorded_at=datetime.now(UTC),
        proofs=(
            ProtectedCheckProof(
                company_id=value.company_id,
                proof_id=uuid4(),
                recipe=target.check_recipe,
                result_artifact=check,
                target_sha256=canonical_sha256(target),
            ),
        ),
    )
    return EngineeringEvidence(
        company_id=value.company_id,
        acceptance=acceptance,
        procedure_id=value.declaration.procedure_id,
        author_registration=value.author_registration,
        verifier_registration=value.verifier_registration,
        author_receipt=receipts[0],
        verifier_receipt=receipts[1],
        author_summary=outputs[0],
        verifier_summary=outputs[1],
        author_utf8=raws[0],
        verifier_utf8=raws[1],
        check=check,
        check_utf8=raw_check,
    )


@dataclass(frozen=True)
class DeliverableCase:
    evidence: EngineeringEvidence
    sources: tuple[CitationCheckSource, ...]
    basis: CycleArtifactBasis
    action_id: UUID
    prepared: PreparedCycleDeliverable

    def command(self) -> CycleArtifactCheckInput:
        outputs = tuple(row.artifact for row in self.prepared.manifest.parts)
        target = VerificationSpec(
            company_id=self.basis.company_id,
            author=self.basis.author,
            verifier=self.basis.verifier,
            action_id=self.action_id,
            proposal_sha256="a" * 64,
            receipt_id=uuid4(),
            receipt_sha256="b" * 64,
            work_snapshot_sha256=self.basis.author_registration_sha256,
            criterion_ids=criteria_for(self.basis.artifact_kind),
            artifacts=outputs,
            check_recipe=f"stockflow-{self.basis.artifact_kind}-v1",
        )
        inputs = self.basis.inputs.model_copy(
            update={"artifacts": (*self.basis.inputs.artifacts, *outputs)}
        )
        return CycleArtifactCheckInput(
            company_id=self.basis.company_id,
            artifact_kind=self.basis.artifact_kind,
            original=self.basis,
            target=target,
            manifest=self.prepared.manifest,
            inputs=inputs,
            typed_json=self.prepared.typed_json,
            human_export=self.prepared.human_export,
        )


def deliverable_case(kind: CycleKind = "presentation") -> DeliverableCase:
    """Keep original source/registration/USD and both outputs in one >50-line data fixture."""
    # Preserve all original source/date/registration/input/output identities in this one fixture.
    evidence = engineering_evidence()
    engineering = compare_engineering_evidence(evidence)
    now = datetime.now(UTC)
    snapshot = strategy_case().command.snapshot
    assert snapshot is not None
    source = snapshot.sources[0]
    source_ref = source.evidence.source.model_copy(update={"company_id": evidence.company_id})
    artifact_ref = source.evidence.artifact.model_copy(update={"company_id": evidence.company_id})
    seconds = source.source_policy.freshness_seconds
    assert seconds is not None
    source = source.model_copy(
        update={
            "evidence": source.evidence.model_copy(
                update={
                    "company_id": evidence.company_id,
                    "source": source_ref,
                    "artifact": artifact_ref,
                }
            ),
            "head": source.head.model_copy(
                update={
                    "company_id": evidence.company_id,
                    "current": source_ref,
                    "observed_at": now - timedelta(seconds=10),
                    "fresh_until": now + timedelta(seconds=seconds - 10),
                }
            ),
        }
    )
    sources = (
        CitationCheckSource(
            evidence=source.evidence,
            head=source.head,
            source_policy=source.source_policy,
            raw_text=source.raw_text,
        ),
    )
    company, workspace = evidence.company_id, evidence.acceptance.target.author.workspace_id
    binding = RunBinding(
        company_id=company,
        workspace_id=workspace,
        actor_id=uuid4(),
        task_id=uuid4(),
        trace_id=uuid4(),
        run_id=uuid4(),
        workflow_name="company.cycle.artifact",
        workflow_version="v1",
        model_profile="routine",
        model_registry_version="supplied-cycle-models-v1",
    )
    verifier = binding.model_copy(
        update={
            "actor_id": uuid4(),
            "task_id": uuid4(),
            "trace_id": uuid4(),
            "run_id": uuid4(),
            "model_profile": "verification",
        }
    )
    goal = snapshot.scope.goal.model_copy(
        update={"company_id": company, "goal_id": engineering.goal_id}
    )
    registration = ExecutionRegistration(
        work=WorkItem(
            company_id=company,
            task_id=binding.task_id,
            trace_id=binding.trace_id,
            goal_id=goal.goal_id,
            department=kind,
            title="Supplied-data internal draft fixture",
            acceptance=criteria_for(kind),
            depends_on=(engineering.acceptance.target.author.task_id,),
            budget_usd=Decimal("0.080000"),
        ),
        run_id=binding.run_id,
        workflow_name=binding.workflow_name,
        workflow_version="v1",
        model_profile="routine",
        model_registry_version=binding.model_registry_version,
        quota=AttemptQuota(model_requests=1, tool_attempts=1, rework_rounds=0, plan_revisions=0),
    )
    inputs = GeneratedArtifactInputs(
        company_id=company,
        artifacts=(
            evidence.author_summary,
            evidence.verifier_summary,
            evidence.check,
            source.evidence.artifact,
        ),
        contributors=(source.evidence.source,),
        evidence=(EvidenceRef(company_id=company, evidence_id=source.evidence.evidence_id),),
        required_resource_ids=snapshot.inputs.required_resource_ids,
    )
    basis = CycleArtifactBasis(
        company_id=company,
        artifact_kind=kind,
        goal=goal,
        producing_plan=PlanRevisionRef(
            company_id=company,
            plan_id=uuid4(),
            plan_revision_id=uuid4(),
            revision=2,
            sha256="c" * 64,
        ),
        procedure_id=engineering.procedure_id,
        author=binding,
        verifier=verifier,
        author_registration=registration,
        author_registration_sha256=registration_digest(registration),
        observed_at=now,
        engineering=engineering,
        inputs=inputs,
        citations=quote_sources(sources, now),
        target=ResourceRef(company_id=company, resource_id=uuid4()),
        data_classification="internal",
    )
    action_id = uuid4()
    prepare = prepare_presentation if kind == "presentation" else prepare_support
    return DeliverableCase(evidence, sources, basis, action_id, prepare(basis, action_id))
