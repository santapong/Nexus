"""Current author preparation cannot borrow owner identity or stale selected native facts."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.scope_support import brain_transaction
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.tests.integration.operating_report_fixture import configured_report
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_operating_reports import (
    reports_factory as reports_factory,
)


@pytest.mark.parametrize("change", ["principal", "trace", "changed_work"])
async def test_author_preparation_requires_actual_signed_binding_and_unchanged_selected_facts(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    change: str,
) -> None:
    from nexus.company.brain.base import BrainReadScope

    scenario = await configured_report(reports_factory, tmp_path)
    author = scenario.saved.selection.author
    scope = BrainReadScope(
        company_id=author.company_id,
        workspace_id=author.workspace_id,
        principal_id=OWNER if change == "principal" else author.actor_id,
        operation_id=uuid4(),
        trace_id=uuid4(),
        task_id=author.task_id,
        task_trace_id=uuid4() if change == "trace" else author.trace_id,
        actor_id=author.actor_id,
    )
    if change == "changed_work":
        await PersistentCompanyDirectory(reports_factory).set_work_active(
            control(),
            task_id=scenario.saved.selection.work[0].task_id,
            active=False,
        )
    with pytest.raises(ValueError):
        async with brain_transaction(reports_factory, scope, identity(scope.principal_id)) as (
            session,
            current,
            _,
        ):
            await scenario.store.prepare_author_output(
                session, current, scope, identity(scope.principal_id), scenario.saved.report_id
            )
