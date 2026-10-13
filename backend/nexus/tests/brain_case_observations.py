"""Actual restricted-PG snapshots remain distinct from sealed synthetic management reports."""

from __future__ import annotations

from pydantic import JsonValue
from sqlalchemy import Table, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import FromClause

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_models import BrainResourceAccess
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.context import AssembledContext
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.models import BrainClaimRevision, BrainRelationshipRevision
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.directory_models import RegisteredWork
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.harness.authorization_models import ActionAuthority
from nexus.harness.journal_models import (
    CompanyControl,
    CostHold,
    DailyBudget,
    JournalAction,
    WorkBudget,
)
from nexus.harness.standing_models import StandingAuthorityGrant, StandingWorkAuthority
from nexus.tests.brain_evaluation_contracts import ObservedSurface
from nexus.tests.brain_projection_fixtures import (
    ActionProjection,
    BudgetProjection,
    EffectProjection,
    EligibilityStateProjection,
    LifetimeProjection,
    NotificationProjection,
    PolicyProjection,
    Projection,
    VerificationProjection,
    WorkProjection,
)

_TABLES: tuple[FromClause, ...] = (
    RegisteredWork.__table__,
    JournalAction.__table__,
    WorkBudget.__table__,
    CostHold.__table__,
    BrainClaimRevision.__table__,
    BrainRelationshipRevision.__table__,
    DailyBudget.__table__,
    ExecutionWork.__table__,
    ExecutionAttempt.__table__,
    EffectIntent.__table__,
    ActionAuthority.__table__,
    StandingWorkAuthority.__table__,
    StandingAuthorityGrant.__table__,
)


async def database_state(
    factory: async_sessionmaker[AsyncSession],
    assembler: PersistentContextAssembler,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    context: AssembledContext,
) -> tuple[dict[str, JsonValue], list[JsonValue]]:
    async with brain_transaction(factory, scope, identity) as (session, control, now):
        await assembler.revalidate_context(session, control, scope, identity, context.manifest, now)
        assert await session.scalar(text("SELECT current_user")) == "nexus_company_app"
        actual: dict[str, JsonValue] = {
            "control": _control(control),
        }
        for table in _TABLES:
            assert isinstance(table, Table)
            count: int | None = await session.scalar(
                select(func.count())
                .select_from(table)
                .where(table.c.company_id == scope.company_id)
            )
            assert isinstance(count, int)
            actual[table.name] = count
        actual["effect_log"] = await _effects(session, scope)
        grants = tuple(
            (
                await session.scalars(
                    select(BrainResourceAccess)
                    .where(
                        BrainResourceAccess.company_id == scope.company_id,
                        BrainResourceAccess.principal_id == scope.principal_id,
                    )
                    .order_by(BrainResourceAccess.resource_id)
                )
            ).all()
        )
        acl: list[JsonValue] = [
            {
                "resource_id": str(row.resource_id),
                "principal_id": str(row.principal_id),
                "active": row.active,
                "generation": row.generation,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            }
            for row in grants
        ]
        return actual, acl


async def _effects(session: AsyncSession, scope: BrainReadScope) -> list[JsonValue]:
    rows = tuple(
        (
            await session.scalars(
                select(EffectIntent)
                .where(
                    EffectIntent.company_id == scope.company_id,
                    EffectIntent.attempt_kind == "tool_attempts",
                )
                .order_by(EffectIntent.action_id)
                .limit(101)
            )
        ).all()
    )
    if len(rows) > 100:
        raise ValueError("Fixture effect audit exceeds its server boundary")
    return [
        {
            "action_id": str(row.action_id),
            "state": row.state,
            "receipt_recorded": row.receipt_json is not None,
        }
        for row in rows
    ]


def _control(control: CompanyControl) -> dict[str, JsonValue]:
    return {
        "owner_id": str(control.owner_id),
        "policy_version": control.policy_version,
        "price_version": control.price_version,
        "paused": control.paused,
        "daily_cap_usd": str(control.daily_cap_usd),
        "work_cap_usd": str(control.work_cap_usd),
    }


def _reported(projections: tuple[Projection, ...], kind: str) -> dict[str, JsonValue]:
    selectors = {
        "authority_state": (BudgetProjection, PolicyProjection),
        "budget_state": (BudgetProjection, LifetimeProjection),
        "work_state": (WorkProjection, EligibilityStateProjection, VerificationProjection),
        "effect_state": (EffectProjection,),
        "notification_state": (NotificationProjection,),
    }
    return next(
        (
            row.fields.model_dump(mode="json")
            for row in projections
            if isinstance(row, selectors.get(kind, ()))
        ),
        {},
    )


def state_surfaces(
    before: dict[str, JsonValue],
    after: dict[str, JsonValue],
    acl_before: list[JsonValue],
    acl_after: list[JsonValue],
    projections: tuple[Projection, ...],
    derived: list[JsonValue],
    logs: str,
) -> tuple[ObservedSurface, ...]:
    names = (
        "authority_state",
        "budget_state",
        "work_state",
        "claim_state",
        "relationship_state",
        "effect_state",
        "notification_state",
    )
    result = [
        ObservedSurface(
            name=name,
            before={**_reported(projections, name), "actual_m1": before},
            after={**_reported(projections, name), "actual_m1": after},
        )
        for name in names
    ]
    result.extend(
        (
            ObservedSurface(name="access_checks", before=acl_before, after=acl_after),
            ObservedSurface(
                name="effect_log", before=before["effect_log"], after=after["effect_log"]
            ),
            ObservedSurface(
                name="notifications", before=before["effect_log"], after=after["effect_log"]
            ),
            ObservedSurface(name="derived_artifacts", before=derived, after=derived),
            ObservedSurface(name="logs", before=logs, after=logs),
        )
    )
    action = next((row for row in projections if isinstance(row, ActionProjection)), None)
    if action is not None:
        fields: dict[str, JsonValue] = {
            "current_revision": action.fields.current_revision,
            "expected_revision": action.fields.expected_revision,
            "may_issue": False,
            "resource": action.fields.resource,
        }
        result.append(ObservedSurface(name="action_checks", before=fields, after=fields))
    return tuple(result)
