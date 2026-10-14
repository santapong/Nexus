"""Actual bounded native leaf charges and exact receipt bindings for report audit."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_support import receipt_artifacts
from nexus.company.management.report_rules import ChargeProjection
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_models import CostHold


async def charge_rows(
    session: AsyncSession, scope: BrainReadScope, ids: tuple[UUID, ...]
) -> tuple[tuple[ChargeProjection, ...], tuple[UUID, ...]]:
    costs = (
        await session.scalars(
            select(CostHold)
            .where(CostHold.company_id == scope.company_id, CostHold.task_id.in_(ids))
            .order_by(CostHold.action_id)
        )
    ).all()
    effects = (
        await session.scalars(
            select(EffectIntent)
            .where(EffectIntent.company_id == scope.company_id, EffectIntent.task_id.in_(ids))
            .order_by(EffectIntent.action_id)
        )
    ).all()
    require_acceptance(len(costs) <= 1000 and len(effects) <= 1000)
    issued = {row.action_id for row in effects}
    result: list[ChargeProjection] = []
    for row in costs:
        registered = await session.get(RegisteredWork, (scope.company_id, row.task_id))
        require_acceptance(registered is not None)
        assert registered is not None
        result.append(
            ChargeProjection.model_validate(
                {
                    "company_id": scope.company_id,
                    "charge_id": row.action_id,
                    "task_id": row.task_id,
                    "root_task_id": registered.root_task_id,
                    "amount_usd": row.amount_usd,
                    "actual_usd": row.actual_usd,
                    "state": row.state,
                    "issued": row.action_id in issued,
                }
            )
        )
    missing = tuple(sorted(issued - {row.action_id for row in costs}))
    return tuple(result), missing


async def latest_receipt(
    session: AsyncSession,
    work: ExecutionWork,
    references: list[ArtifactRevisionRef],
) -> ActionReceipt | None:
    effects = (
        await session.scalars(
            select(EffectIntent)
            .where(
                EffectIntent.company_id == work.company_id,
                EffectIntent.task_id == work.task_id,
            )
            .order_by(EffectIntent.created_at, EffectIntent.action_id)
        )
    ).all()
    require_acceptance(len(effects) <= 1000)
    latest = None
    for effect in effects:
        require_acceptance(
            (effect.task_id, effect.trace_id, effect.run_id)
            == (work.task_id, work.trace_id, work.run_id)
        )
        if effect.receipt_json:
            latest = ActionReceipt.model_validate_json(effect.receipt_json)
            require_acceptance(
                (
                    latest.company_id,
                    latest.action_id,
                    latest.task_id,
                    latest.trace_id,
                    latest.proposal_hash,
                )
                == (
                    work.company_id,
                    effect.action_id,
                    work.task_id,
                    work.trace_id,
                    effect.proposal_hash,
                )
            )
            if latest.artifacts:
                references.extend(await receipt_artifacts(session, latest))
    return latest
