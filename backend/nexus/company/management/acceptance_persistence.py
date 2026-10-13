"""Immutable acceptance/proof row encoding; caller holds the actual company transaction."""

from datetime import datetime
from uuid import uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.management.acceptance import ProtectedCheckProof, WorkAcceptance
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_evidence import PreparedReportCheck
from nexus.company.management.acceptance_models import (
    ManagementAcceptanceProof,
    ManagementWorkAcceptance,
)
from nexus.company.management.canonical import canonical_sha256


def acceptance_record(row: ManagementWorkAcceptance) -> WorkAcceptance:
    record = WorkAcceptance.model_validate_json(row.result_json)
    target = record.target
    require_acceptance(
        record.company_id == row.company_id
        and record.acceptance_id == row.acceptance_id
        and record.verdict == row.verdict
        and canonical_sha256(target) == row.target_sha256
        and target.model_dump_json() == row.target_json
        and (
            target.author.task_id,
            target.author.run_id,
            target.author.actor_id,
            target.verifier.task_id,
            target.verifier.run_id,
            target.verifier.actor_id,
            target.action_id,
            target.receipt_id,
            target.receipt_sha256,
            target.work_snapshot_sha256,
        )
        == (
            row.author_task_id,
            row.author_run_id,
            row.author_id,
            row.verifier_task_id,
            row.verifier_run_id,
            row.verifier_id,
            row.action_id,
            row.receipt_id,
            row.receipt_sha256,
            row.work_sha256,
        )
    )
    return record


async def write_acceptance(session: AsyncSession, record: WorkAcceptance) -> None:
    target = record.target
    session.add(
        ManagementWorkAcceptance(
            company_id=record.company_id,
            acceptance_id=record.acceptance_id,
            author_task_id=target.author.task_id,
            author_run_id=target.author.run_id,
            author_id=target.author.actor_id,
            verifier_task_id=target.verifier.task_id,
            verifier_run_id=target.verifier.run_id,
            verifier_id=target.verifier.actor_id,
            action_id=target.action_id,
            receipt_id=target.receipt_id,
            receipt_sha256=target.receipt_sha256,
            work_sha256=target.work_snapshot_sha256,
            target_sha256=canonical_sha256(target),
            verdict=record.verdict,
            target_json=target.model_dump_json(),
            result_json=record.model_dump_json(),
            recorded_at=record.recorded_at,
        )
    )
    await session.flush()
    for proof in record.proofs:
        session.add(
            ManagementAcceptanceProof(
                company_id=record.company_id,
                acceptance_id=record.acceptance_id,
                proof_id=proof.proof_id,
                artifact_revision_id=proof.result_artifact.artifact_revision_id,
                artifact_sha256=proof.result_artifact.sha256,
                check_recipe=proof.recipe,
                target_sha256=proof.target_sha256,
                proof_json=proof.model_dump_json(),
            )
        )
    await session.flush()


def build_acceptance(prepared: PreparedReportCheck, now: datetime) -> WorkAcceptance:
    target = prepared.command.target
    target_hash = canonical_sha256(target)
    acceptance_id = uuid5(target.company_id, f"management.acceptance:{target_hash}")
    return WorkAcceptance(
        company_id=target.company_id,
        acceptance_id=acceptance_id,
        target=target,
        verdict=prepared.result.verdict,
        recorded_at=now,
        limitations=prepared.result.limitations,
        proofs=(
            ProtectedCheckProof(
                company_id=target.company_id,
                proof_id=uuid5(acceptance_id, prepared.protected.artifact.artifact_revision_id.hex),
                recipe=target.check_recipe,
                target_sha256=target_hash,
                result_artifact=prepared.protected.artifact,
            ),
        ),
    )
