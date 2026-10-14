"""Actual configured actor/work/source admission for pending action preparation, never issuance."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.control_support import current_charter
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactPayload,
    GeneratedArtifactRule,
)
from nexus.company.management.generated_artifact_privacy import GeneratedProtection, protect_inputs
from nexus.company.management.governance import CharterRevision
from nexus.company.management.native_profile_contracts import NativeReportProfileRef
from nexus.company.management.native_profile_lookup import load_profile
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import PlanAdmissionCatalog, validate_plan_profile
from nexus.company.management.plans import ChildAllocation, RunBinding
from nexus.company.management.report_inputs import native_author
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.management_checks import require_management_execution
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    require_lease,
    require_runtime_scope,
)
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl


@dataclass(frozen=True)
class PreparedAdmission:
    binding: RunBinding
    child: ChildAllocation
    charter: CharterRevision
    protection: GeneratedProtection
    lease_until: datetime | None = None

    def require_time(self, catalog: PlanAdmissionCatalog, now: datetime) -> None:
        self.protection.require_time(now)
        validate_plan_profile(catalog, self.child, now)
        if self.lease_until is not None and self.lease_until <= now:
            raise ManagementDeniedError("Actual verifier lease expired during preparation")


def control_scope(scope: BrainReadScope) -> CompanyControlScope:
    """Retain the signed actor's audit scope; never manufacture owner authority."""
    return CompanyControlScope(
        company_id=scope.company_id,
        principal_id=scope.principal_id,
        operation_id=scope.operation_id,
        trace_id=scope.trace_id,
    )


def ledger_scope(binding: RunBinding) -> LedgerScope:
    """Retain exact registered actor/task/trace for the company mutex transaction."""
    return LedgerScope(
        company_id=binding.company_id,
        principal_id=binding.actor_id,
        task_id=binding.task_id,
        trace_id=binding.trace_id,
    )


def _require_actor(work: ExecutionWork, expected: RunBinding, identity: VerifiedIdentity) -> None:
    if (
        native_author(work)[0] != expected
        or identity.principal_id != expected.actor_id
        or identity.workspace_id != expected.workspace_id
    ):
        raise ManagementDeniedError(
            "Native preparation actor differs from its actual approved work"
        )


async def admit_preparation(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    reference: NativeReportProfileRef,
    phase: Literal["author", "verifier"],
    prepared: GeneratedArtifactPayload,
    rule: GeneratedArtifactRule,
    catalog: PlanAdmissionCatalog,
    reader: BoundedArtifactReader,
    freshness: RegisteredSourceFreshness,
    lease: ExecutionLease | None = None,
) -> PreparedAdmission:
    """Read and revalidate current native admission without issuing any effect permit."""
    audit, now = control_scope(scope), await db_now(session)
    profile, _ = await load_profile(session, control, audit, reference, require_due=True, now=now)
    expected = profile.selection.author if phase == "author" else profile.selection.verifier
    work = await execution_row(session, ledger_scope(expected))
    _require_actor(work, expected, identity)
    await require_runtime_scope(
        session, control, ledger_scope(expected), identity, allow_inactive=False, owner_read=False
    )
    await require_management_execution(session, control, work, identity, catalog, reader, freshness)
    if phase == "verifier":
        if lease is None:
            raise ManagementDeniedError("Verifier preparation requires its actual execute lease")
        require_lease(work, lease, await db_now(session), execute=True)
    bound = await ManagementPlanStore.current_binding(
        session, expected.company_id, expected.task_id
    )
    if bound is None or bound.plan != profile.selection.plan or bound.child.binding != expected:
        raise ManagementDeniedError("Native preparation plan/work binding is no longer current")
    protection = await protect_inputs(
        session, control, scope, identity, prepared, rule, reader, freshness
    )
    charter = await current_charter(session, control_scope(scope), bound.child.charter)
    result = PreparedAdmission(
        expected,
        bound.child,
        charter,
        protection,
        work.lease_until if phase == "verifier" else None,
    )
    result.require_time(catalog, await db_now(session))
    return result
