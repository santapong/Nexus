"""Actual physical015 capability on closed015/016/017 profiles, before full event SQL."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.native_event_schema import NATIVE_EVENT_FIELDS
from nexus.company.brain.scope_support import BrainDeniedError


async def native_event_capability(session: AsyncSession) -> bool:
    """Partial columns fail closed; old008/014 still use only their original event SQL."""
    columns = set(
        (
            await session.execute(
                text(
                    "SELECT attname FROM pg_attribute WHERE "
                    "attrelid=to_regclass('public.company_brain_events') "
                    "AND attnum > 0 AND NOT attisdropped"
                )
            )
        ).scalars()
    )
    present = columns.intersection(NATIVE_EVENT_FIELDS)
    if not present:
        return False
    if present != set(NATIVE_EVENT_FIELDS):
        raise BrainDeniedError("Native event schema is incomplete")
    if await session.scalar(text("SELECT to_regclass('public.company_alembic_version')")) is None:
        raise BrainDeniedError("Native event profile is not qualified")
    version = await session.scalar(text("SELECT version_num FROM company_alembic_version"))
    if not isinstance(version, str) or version not in {"company_015", "company_016", "company_017"}:
        raise BrainDeniedError("Native event profile version is not qualified")
    return True
