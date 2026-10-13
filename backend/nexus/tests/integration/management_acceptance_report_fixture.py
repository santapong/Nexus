"""Actual owner-basis, selected approved-procedure report fixture arithmetic.

The verifier checks an explicitly shared report procedure; this server-owned test
lookup reads actual owner/report facts and never accepts caller role/auth flags.
All selected work/charges use the protected admitted company.report resource.
This provider is fixture-only, not a production general company-report loader.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import Capability, PrincipalAccess, VerifiedIdentity, require_capability
from nexus.company.brain.artifact_contracts import ArtifactSlice
from nexus.company.brain.base import BrainReadScope, ValueContract
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.contracts.results import ActionReceipt
from nexus.company.directory_models import DirectoryCompany, DirectoryMembership
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.eligibility_rules import (
    AcceptedWork,
    CurrentReadGrant,
    PublishedAcceptance,
)
from nexus.company.management.plans import PlanPayload, RunBinding
from nexus.company.management.report_rules import (
    ChargeProjection,
    ReportInput,
    ReportScope,
    WorkLineage,
    WorkReportFacts,
)
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import snapshot
from nexus.harness.journal_models import CompanyControl, CostHold


class ChargeSnapshot(ValueContract):
    charges: tuple[ChargeProjection, ...]


def charge_digest(charges: tuple[ChargeProjection, ...]) -> str:
    return canonical_sha256(ChargeSnapshot(charges=charges))


def bindings(payload: PlanPayload) -> tuple[RunBinding, RunBinding, RunBinding]:
    edge = payload.verification[0]
    author = next(
        row.binding for row in payload.children if row.binding.task_id == edge.author_task_id
    )
    verifier = next(
        row.binding for row in payload.children if row.binding.task_id == edge.verifier_task_id
    )
    return payload.procedure.binding, author, verifier


async def owner_report_access(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
) -> PrincipalAccess:
    await require_brain_scope(session, control, scope, identity)
    company = await session.get(DirectoryCompany, scope.company_id)
    owner = await session.get(DirectoryMembership, (scope.company_id, control.owner_id))
    assert company is not None and owner is not None and company.owner_id == control.owner_id
    access = PrincipalAccess.model_validate(
        {
            "company_id": company.company_id,
            "workspace_id": company.workspace_id,
            "principal_id": owner.principal_id,
            "owner_id": company.owner_id,
            "membership_role": owner.role,
            "company_active": company.company_active,
            "workspace_active": company.workspace_active,
            "principal_active": owner.principal_active,
            "membership_active": owner.membership_active,
        }
    )
    require_capability(access, Capability.READ)
    return access


async def report_facts(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    source: ArtifactSlice,
    observed: datetime,
    payload: PlanPayload,
) -> ReportInput:
    access = await owner_report_access(session, control, scope, identity)
    root, author, _ = bindings(payload)
    charges = (
        await session.scalars(select(CostHold).where(CostHold.company_id == scope.company_id))
    ).all()
    work_rows: list[WorkReportFacts] = []
    for binding in (child.binding for child in payload.children):
        row = await session.get(ExecutionWork, (scope.company_id, binding.task_id))
        assert row is not None
        actual = snapshot(row)
        effects = (
            await session.scalars(
                select(EffectIntent).where(
                    EffectIntent.company_id == scope.company_id,
                    EffectIntent.task_id == binding.task_id,
                )
            )
        ).all()
        receipt = (
            ActionReceipt.model_validate_json(effects[0].receipt_json)
            if effects and effects[0].receipt_json
            else None
        )
        acceptance = AcceptedWork(
            company_id=scope.company_id,
            work=binding,
            work_snapshot_sha256=row.registration_hash,
            criterion_ids=actual.registration.work.acceptance,
            publication=PublishedAcceptance(
                company_id=scope.company_id,
                acceptance=None,
                trusted_proofs_resolved=False,
                invalidated=False,
            ),
        )
        work_rows.append(
            WorkReportFacts.model_validate(
                {
                    "company_id": scope.company_id,
                    "work": binding,
                    "execution_state": row.state,
                    "registered_active": True,
                    "cancelled": False,
                    "acceptance": acceptance,
                    "receipt": receipt,
                    "verification_candidate": None,
                    "required_resources": tuple(value.resource_id for value in source.contributors),
                }
            )
        )
    return ReportInput(
        company_id=scope.company_id,
        report_id=author.run_id,
        scope=ReportScope(
            company_id=scope.company_id,
            access=access,
            company_report=True,
            grants=tuple(
                CurrentReadGrant(
                    company_id=scope.company_id,
                    resource_id=row.resource_id,
                    expected_generation=row.generation,
                    current_generation=row.generation,
                    resource_active=True,
                    grant_active=True,
                    expires_at=row.expires_at,
                    source_current=True,
                )
                for row in source.contributors
            ),
        ),
        period_start=observed - timedelta(hours=1),
        period_end=observed + timedelta(hours=1),
        observed_at=observed,
        ledger_source_sha256=charge_digest(
            tuple(charge_fact(row, source, root.task_id) for row in charges)
        ),
        lineage=tuple(
            WorkLineage(
                company_id=scope.company_id,
                work=binding,
                parent_task_id=None if binding == root else root.task_id,
                root_task_id=root.task_id,
            )
            for binding in (root, *(child.binding for child in payload.children))
        ),
        work=tuple(work_rows),
        charges=tuple(charge_fact(row, source, root.task_id) for row in charges),
    )


def charge_fact(row: CostHold, source: ArtifactSlice, root_id: UUID) -> ChargeProjection:
    return ChargeProjection.model_validate(
        {
            "company_id": row.company_id,
            "charge_id": row.action_id,
            "task_id": row.task_id,
            "root_task_id": root_id,
            "amount_usd": row.amount_usd,
            "actual_usd": row.actual_usd,
            "state": row.state,
            "issued": row.state != "held",
            "required_resources": tuple(value.resource_id for value in source.contributors),
        }
    )


def declared_candidate(
    facts: ReportInput, receipt: ActionReceipt, payload: PlanPayload
) -> ReportInput:
    """An authored fixture report anticipates stated values; the real loader verifies them.

    This is candidate output, not input to the trusted loader. Changing the actual
    recorded cost/outcome later makes the independent mechanical check reject.
    """
    _, author, verifier = bindings(payload)
    rows = tuple(
        row.model_copy(update={"execution_state": "verifying", "receipt": receipt})
        if row.work == author
        else row.model_copy(update={"execution_state": "running"})
        if row.work == verifier
        else row
        for row in facts.work
    )
    charges = tuple(
        row.model_copy(
            update={"state": "reconciled", "actual_usd": Decimal("0.025000"), "issued": True}
        )
        for row in facts.charges
    )
    return ReportInput.model_validate_json(
        facts.model_copy(
            update={
                "work": rows,
                "charges": charges,
                "ledger_source_sha256": charge_digest(charges),
            }
        ).model_dump_json()
    )
