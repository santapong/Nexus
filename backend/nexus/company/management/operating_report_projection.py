"""Real-owner projection; shared reads compare native facts without owner impersonation."""

from datetime import datetime
from uuid import UUID

from nexus.company.access import PrincipalAccess
from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.eligibility_rules import CurrentReadGrant
from nexus.company.management.operating_report_contracts import ReportData
from nexus.company.management.report_rules import (
    OperatingProjection,
    ReportInput,
    ReportScope,
    project_report,
)


def owner_projection(
    data: ReportData,
    access: PrincipalAccess,
    report_id: UUID,
    start: datetime,
    end: datetime,
    observed_at: datetime,
    grants: tuple[ResourceGeneration, ...],
) -> OperatingProjection:
    facts = ReportInput(
        company_id=data.company_id,
        report_id=report_id,
        scope=projection_scope(data, access, grants),
        period_start=start,
        period_end=end,
        observed_at=observed_at,
        ledger_source_sha256=canonical_sha256(data),
        lineage=data.lineage,
        work=data.work,
        charges=data.charges,
        owner_decision_ids=data.owner_decision_ids,
    )
    result = project_report(facts)
    unknown = tuple(sorted({*result.unknown_charge_ids, *data.missing_charge_ids}))
    blockers = tuple(
        dict.fromkeys(
            (
                *result.snapshot.blockers,
                *data.blockers,
                *(("billing_reservation_missing",) if data.missing_charge_ids else ()),
            )
        )
    )
    snapshot = result.snapshot.model_copy(
        update={"blockers": blockers, "owner_decision_ids": data.owner_decision_ids}
    )
    return OperatingProjection.model_validate_json(
        result.model_copy(
            update={
                "snapshot": snapshot,
                "unknown_charge_ids": unknown,
                "actual_total_usd": None if unknown else result.actual_total_usd,
            }
        ).model_dump_json()
    )


def projection_scope(
    data: ReportData, access: PrincipalAccess, grants: tuple[ResourceGeneration, ...]
) -> ReportScope:
    return ReportScope(
        company_id=data.company_id,
        access=access,
        company_report=False,
        allowed_task_ids=tuple(row.work.task_id for row in data.work),
        grants=tuple(
            CurrentReadGrant(
                company_id=data.company_id,
                resource_id=row.resource_id,
                expected_generation=row.generation,
                current_generation=row.generation,
                resource_active=True,
                grant_active=True,
                source_current=True,
                expires_at=row.expires_at,
            )
            for row in grants
        ),
    )
