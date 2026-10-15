"""Read-only exact saved Strategy acceptance/proof rows; no latest-success fallback or repair."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_models import (
    ManagementAcceptanceInvalidation,
    ManagementAcceptanceProof,
    ManagementWorkAcceptance,
)
from nexus.company.management.acceptance_persistence import acceptance_record
from nexus.company.strategy.contracts import (
    STRATEGY_CHECK_CRITERIA,
    STRATEGY_CHECK_RECIPE,
    StrategySelectionRef,
)


async def load_selected_acceptance_locked(
    session: AsyncSession,
    selection: StrategySelectionRef,
) -> WorkAcceptance:
    """An explicit selection must name its one immutable, uninvalidated native proof."""
    require_acceptance(session.in_transaction())
    row = await session.get(
        ManagementWorkAcceptance, (selection.company_id, selection.acceptance_id)
    )
    require_acceptance(row is not None)
    assert row is not None
    record = acceptance_record(row)
    require_acceptance(
        row.recorded_at == record.recorded_at
        and record.company_id == selection.company_id
        and record.acceptance_id == selection.acceptance_id
        and record.verdict == "pass"
        and len(record.proofs) == 1
        and record.target.artifacts == (selection.brief,)
        and record.target.check_recipe == STRATEGY_CHECK_RECIPE
        and record.target.criterion_ids == STRATEGY_CHECK_CRITERIA
    )
    invalid = await session.scalar(
        select(ManagementAcceptanceInvalidation.invalidation_id)
        .where(
            ManagementAcceptanceInvalidation.company_id == selection.company_id,
            ManagementAcceptanceInvalidation.acceptance_id == selection.acceptance_id,
        )
        .limit(1)
    )
    require_acceptance(invalid is None)
    proofs = tuple(
        (
            await session.scalars(
                select(ManagementAcceptanceProof)
                .where(
                    ManagementAcceptanceProof.company_id == record.company_id,
                    ManagementAcceptanceProof.acceptance_id == record.acceptance_id,
                )
                .limit(2)
            )
        ).all()
    )
    require_acceptance(len(proofs) == 1)
    value, expected = proofs[0], record.proofs[0]
    require_acceptance(
        (
            value.company_id,
            value.acceptance_id,
            value.proof_id,
            value.artifact_revision_id,
            value.artifact_sha256,
            value.check_recipe,
            value.target_sha256,
            value.proof_json,
        )
        == (
            record.company_id,
            record.acceptance_id,
            expected.proof_id,
            expected.result_artifact.artifact_revision_id,
            expected.result_artifact.sha256,
            expected.recipe,
            expected.target_sha256,
            expected.model_dump_json(),
        )
    )
    return record
