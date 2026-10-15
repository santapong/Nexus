"""Current native strategy application role gate; no caller-supplied privilege claim."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.management.acceptance_errors import require_acceptance


async def require_strategy_application_role(session: AsyncSession) -> None:
    """A configured privileged connection must not bypass company row-security checks."""
    require_acceptance(session.in_transaction())
    privileged = await session.scalar(
        text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
    )
    require_acceptance(privileged is False)
