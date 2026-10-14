"""Pure constructed check inputs; no database, model, engine or acceptance authority."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from nexus.builder.engineering_contracts import (
    ENGINEERING_CRITERIA,
    ENGINEERING_RECIPE,
    EngineeringChangeDeclaration,
    EngineeringChangedFile,
    EngineeringCheckInput,
    EngineeringSourceWitness,
)
from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.result_codec import captured
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.contracts.work import WorkItem
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plans import RunBinding
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionRegistration
from nexus.execution.runtime_support import registration_digest
from nexus.tests.builder_support import described_job, described_policy


def check_input() -> EngineeringCheckInput:
    original = described_job()
    policy = described_policy()
    goal = uuid4()
    source = ArtifactRevisionRef(
        company_id=original.company_id,
        artifact_id=uuid4(),
        artifact_revision_id=uuid4(),
        revision="fixture-patch-v1",
        sha256="9" * 64,
        byte_length=100,
    )
    specs, bindings, registrations, outputs, receipts, results, witnesses = (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    )
    for name, profile in (
        ("engineering.change", "engineering.native.v1"),
        ("engineering.verify", "verification.native.v1"),
    ):
        job = original.model_copy(
            update={
                "task_id": uuid4(),
                "trace_id": uuid4(),
                "run_id": uuid4(),
                "actor_id": uuid4(),
                "action_id": uuid4(),
                "patch_sha256": source.sha256,
            }
        )
        spec = BuilderExecutionSpec(
            job=job, policy_sha256=canonical_sha256(policy), protected_patch=source
        )
        bound = RunBinding(
            company_id=job.company_id,
            task_id=job.task_id,
            trace_id=job.trace_id,
            actor_id=job.actor_id,
            run_id=job.run_id,
            workspace_id=job.workspace_id,
            workflow_name=name,
            workflow_version="v1",
            model_profile=profile,
            model_registry_version="native.fixture.v1",
        )
        registration = ExecutionRegistration(
            work=WorkItem(
                company_id=job.company_id,
                task_id=job.task_id,
                trace_id=job.trace_id,
                goal_id=goal,
                department="engineering",
                title="Synthetic quantity fixture",
                acceptance=ENGINEERING_CRITERIA,
                budget_usd=Decimal("0.1"),
            ),
            run_id=job.run_id,
            workflow_name=name,
            workflow_version="v1",
            model_profile=profile,
            model_registry_version="native.fixture.v1",
            quota=AttemptQuota(
                model_requests=0, tool_attempts=1, rework_rounds=0, plan_revisions=0
            ),
        )
        output = ArtifactRevisionRef(
            company_id=job.company_id,
            artifact_id=uuid4(),
            artifact_revision_id=uuid4(),
            revision="fixture-native-v1",
            sha256="7" * 64,
            byte_length=1000,
        )
        receipt = ActionReceipt(
            company_id=job.company_id,
            receipt_id=uuid4(),
            action_id=job.action_id,
            task_id=job.task_id,
            trace_id=job.trace_id,
            proposal_hash="6" * 64,
            outcome="succeeded",
            recorded_at=datetime.now(UTC),
            artifacts=(
                ArtifactRef(
                    company_id=job.company_id,
                    artifact_id=output.artifact_id,
                    reference="fixture-native",
                    sha256=output.sha256,
                    revision=output.revision,
                ),
            ),
        )
        from nexus.builder.contracts import BuilderCommandReceipt

        result = BuilderRunResult(
            spec=spec,
            proposal_sha256=receipt.proposal_hash,
            intent_fence=1,
            image_id="1" * 64,
            container_name="nexus-builder-" + "d" * 32,
            outcome="commands_succeeded",
            commands=tuple(
                BuilderCommandReceipt(
                    command_key=row.command_key,
                    phase=row.phase,
                    exit_code=0,
                    outcome="exited",
                    elapsed_millis=1,
                )
                for row in job.commands
            ),
            artifacts=(
                captured("baseline/checks/value", b"baseline"),
                captured(
                    "post/checks/behavior.json",
                    b'{"schema_version":"nexus.engineering.behavior.v1","cases":[{"case_id":"fixture.quantity.v1","status":"pass"}]}',
                ),
            ),
            observed_memory_max=4294967296,
            observed_cpu_quota=200000,
            observed_cpu_period=100000,
            observed_pids_max=256,
            recorded_at=datetime.now(UTC),
            elapsed_millis=2,
        )
        witness = EngineeringSourceWitness(
            spec_sha256=canonical_sha256(spec),
            source=job.source,
            patch_sha256=source.sha256,
            baseline_inventory_sha256="2" * 64,
            post_inventory_sha256="3" * 64,
            changes=(
                EngineeringChangedFile(
                    path="apps/web/src/value.ts", before_sha256="4" * 64, after_sha256="5" * 64
                ),
            ),
        )
        specs.append(spec)
        bindings.append(bound)
        registrations.append(registration)
        outputs.append(output)
        receipts.append(receipt)
        results.append(result)
        witnesses.append(witness)
    target = VerificationSpec(
        company_id=original.company_id,
        author=bindings[0],
        verifier=bindings[1],
        action_id=receipts[0].action_id,
        proposal_sha256=receipts[0].proposal_hash,
        receipt_id=receipts[0].receipt_id,
        receipt_sha256=canonical_sha256(receipts[0]),
        work_snapshot_sha256=registration_digest(registrations[0]),
        criterion_ids=ENGINEERING_CRITERIA,
        artifacts=(outputs[0],),
        check_recipe=ENGINEERING_RECIPE,
    )
    declaration = EngineeringChangeDeclaration(
        company_id=original.company_id,
        goal_id=goal,
        procedure_id=uuid4(),
        policy=policy,
        image_id="1" * 64,
        behavior_case_ids=("fixture.quantity.v1",),
    )
    return EngineeringCheckInput(
        company_id=original.company_id,
        target=target,
        declaration=declaration,
        author=results[0],
        verifier=results[1],
        author_receipt=receipts[0],
        verifier_receipt=receipts[1],
        author_registration=registrations[0],
        verifier_registration=registrations[1],
        author_output=outputs[0],
        verifier_output=outputs[1],
        author_witness=witnesses[0],
        verifier_witness=witnesses[1],
    )
