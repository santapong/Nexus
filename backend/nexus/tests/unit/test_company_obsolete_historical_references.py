"""Pure metadata boundary checks never establish historical source authority or native progress."""

from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import BlobReader
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.brain.obsolete_native_provenance import qualify_obsolete_native_inputs
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.management import historical_reference_provenance
from nexus.company.management.historical_reference_provenance import historical_reference_sources
from nexus.harness.journal_models import CompanyControl
from nexus.tests.unit.test_company_management_contracts import artifact


def scope() -> BrainReadScope:
    return BrainReadScope(
        company_id=UUID(int=1),
        workspace_id=UUID(int=2),
        principal_id=UUID(int=3),
        operation_id=UUID(int=4),
        trace_id=UUID(int=5),
    )


async def test_locked_historical_reader_rejects_missing_transaction_before_any_factory() -> None:
    factory = MagicMock(spec=async_sessionmaker)
    blobs = MagicMock(spec=BlobReader)
    reader = BoundedArtifactReader(cast(async_sessionmaker[AsyncSession], factory), blobs)
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = False
    with pytest.raises(BrainDeniedError):
        await reader.revalidate_historical_artifact_reference(
            session,
            CompanyControl(company_id=scope().company_id),
            scope(),
            VerifiedIdentity(principal_id=scope().principal_id, workspace_id=scope().workspace_id),
            artifact(),
            datetime.now(UTC),
        )
    factory.assert_not_called()
    blobs.read.assert_not_called()


@pytest.mark.parametrize("kind", ["empty", "duplicate", "foreign"])
async def test_historical_resolver_denies_bad_full_references_before_closure(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = artifact()
    references = (
        ()
        if kind == "empty"
        else (value, value)
        if kind == "duplicate"
        else (value.model_copy(update={"company_id": UUID(int=999)}),)
    )
    closure = AsyncMock()
    monkeypatch.setattr(historical_reference_provenance, "report_resources", closure)
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    with pytest.raises(ValueError):
        await historical_reference_sources(session, scope(), references)
    closure.assert_not_called()


@pytest.mark.parametrize("expired", [False, True])
async def test_obsolete_qualifier_retains_historical_deadlines_and_never_calls_current_method(
    expired: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.company.brain import obsolete_native_provenance as module

    now = datetime.now(UTC)
    deadline = now + timedelta(seconds=-1 if expired else 30)
    services = MagicMock(spec=NativeFactServices)
    services.catalog = MagicMock()
    services.catalog.company_id = scope().company_id
    services.artifacts = MagicMock()
    services.freshness = MagicMock()
    services.artifacts.revalidate_historical_artifact_reference = AsyncMock(
        return_value=(deadline,)
    )
    services.artifacts.revalidate_artifact_reference = AsyncMock(
        side_effect=AssertionError("current path")
    )
    services.freshness.revalidate_historical_references = AsyncMock(return_value=(deadline,))
    monkeypatch.setattr(
        module, "report_resources", AsyncMock(return_value=((UUID(int=20),), (), ()))
    )
    monkeypatch.setattr(module, "require_resources", AsyncMock(return_value=()))
    monkeypatch.setattr(module, "db_now", AsyncMock(return_value=now))
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    operation = qualify_obsolete_native_inputs(
        session,
        CompanyControl(company_id=scope().company_id),
        scope(),
        VerifiedIdentity(principal_id=scope().principal_id, workspace_id=scope().workspace_id),
        services,
        (UUID(int=20),),
        (artifact(),),
    )
    if expired:
        with pytest.raises(BrainDeniedError):
            await operation
    else:
        required, deadlines = await operation
        assert required == (UUID(int=20),) and deadlines == (deadline,)
    services.artifacts.revalidate_artifact_reference.assert_not_called()
