"""Explicit registered digest buckets from the real Bangkok clock and current saved facts."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.native_fact_contracts import DigestSelector, DigestState
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.operating_report_capture import capture_data
from nexus.company.management.operating_report_store import stored_report
from nexus.company.management.operation_models import ManagementReportSnapshot
from nexus.harness.journal_models import CompanyControl


def digest_window(kind: str, now: datetime) -> tuple[str, datetime] | None:
    """One daily date / current Monday bucket, never a minute UUID or caller-selected date."""
    if kind not in {"daily", "weekly"} or now.utcoffset() is None:
        raise ValueError("Digest clock/kind is unavailable")
    local = now.astimezone(ZoneInfo("Asia/Bangkok"))
    day = local.date() - timedelta(days=local.weekday()) if kind == "weekly" else local.date()
    scheduled = datetime.combine(day, time(9), tzinfo=local.tzinfo)
    return (f"{kind}:{day.isoformat()}", scheduled) if now >= scheduled else None


async def digest_state(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    selector: DigestSelector,
    services: NativeFactServices,
    now: datetime,
) -> DigestState | None:
    registered = next((row for row in services.digests if row.schedule == selector.schedule), None)
    if registered is None or not registered.registered_at <= now < registered.expires_at:
        raise BrainDeniedError("Registered native digest schedule is unavailable")
    policy = registered.policy
    if control.paused or not policy.enabled or not getattr(policy, f"{registered.kind}_digest"):
        return None
    window = digest_window(registered.kind, now)
    if window is None:
        return None
    row = await session.get(ManagementReportSnapshot, (scope.company_id, registered.report_id))
    if row is None:
        raise BrainDeniedError("Registered native digest report is unavailable")
    saved = stored_report(row)
    if saved.created_by != control.owner_id:
        raise BrainDeniedError("Registered native digest owner report is unavailable")
    data = await capture_data(
        session,
        control,
        scope,
        identity,
        saved.selection,
        services.catalog,
        services.artifacts,
        services.freshness,
    )
    if canonical_sha256(data) != saved.data_sha256:
        return None
    return DigestState(
        company_id=scope.company_id,
        saved=saved,
        registration=registered,
        due_bucket=window[0],
        scheduled_for=window[1],
    )
