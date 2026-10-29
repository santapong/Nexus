"""Generated reports remain protected at recipient and freshness boundaries."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.brain.sources import SourceHead, SourceRevisionRef
from nexus.company.management import generated_artifact_privacy as privacy
from nexus.company.management.generated_artifact_privacy import GeneratedProtection

# TASK: Check report readership, exact expiry and source freshness boundaries.
# FILES TO CREATE: nexus/tests/unit/test_generated_artifact_recipient_protection.py
# TESTS: Current/expired grants and heads, membership, bounded recipient intersection.
# DONE: Relevant denial and successful paths pass without a live database.
# RISK: Low; these are isolated tests of the existing authorization boundary.

NOW = datetime(2026, 10, 29, tzinfo=UTC)


def _grant(company: UUID, expires_at: datetime | None) -> ResourceGeneration:
    return ResourceGeneration(
        company_id=company, resource_id=uuid4(), generation=1, expires_at=expires_at
    )


def _head(company: UUID, availability: str, fresh_until: datetime | None) -> SourceHead:
    source = uuid4()
    return SourceHead.model_validate(
        {
            "company_id": company,
            "source_id": source,
            "current": SourceRevisionRef(
                company_id=company, source_id=source, source_revision_id=uuid4(), revision="r1"
            ),
            "generation": 1,
            "observed_at": NOW - timedelta(days=1),
            "fresh_until": fresh_until,
            "availability": availability,
        }
    )


def test_current_grant_and_available_source_pass_until_the_exact_expiry() -> None:
    company = uuid4()
    end = NOW + timedelta(seconds=1)
    proof = GeneratedProtection(
        grants=(_grant(company, end),), heads=(_head(company, "available", end),)
    )
    proof.require_time(NOW)
    with pytest.raises(BrainDeniedError, match="expired"):
        proof.require_time(end)


def test_no_ttl_is_not_invented_as_expired() -> None:
    company = uuid4()
    proof = GeneratedProtection(
        grants=(_grant(company, None),), heads=(_head(company, "available", None),)
    )
    proof.require_time(NOW)


@pytest.mark.parametrize("availability", ["quarantined", "unavailable"])
def test_unavailable_source_denies_even_with_an_unexpired_grant(availability: str) -> None:
    company = uuid4()
    proof = GeneratedProtection(
        grants=(_grant(company, NOW + timedelta(days=1)),),
        heads=(_head(company, availability, NOW + timedelta(days=1)),),
    )
    with pytest.raises(BrainDeniedError, match="expired"):
        proof.require_time(NOW)


def _scope(company: UUID) -> BrainReadScope:
    return BrainReadScope(
        company_id=company,
        workspace_id=uuid4(),
        principal_id=uuid4(),
        operation_id=uuid4(),
        trace_id=uuid4(),
    )


def _session(principals: list[UUID], member: object) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.all.return_value = [SimpleNamespace(principal_id=value) for value in principals]
    session.scalars.return_value = result
    session.get.return_value = member
    return session


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 33])
async def test_recipient_count_must_be_nonempty_and_bounded(count: int) -> None:
    scope = _scope(uuid4())
    session = _session([uuid4() for _ in range(count)], None)
    with pytest.raises(BrainDeniedError, match="bounded actual current readership"):
        await privacy.recipients(cast(AsyncSession, session), scope, uuid4(), (uuid4(),), NOW)
    session.get.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("member", [None, (False, True), (True, False)])
async def test_inactive_recipient_denies_the_complete_audience(
    member: tuple[bool, bool] | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = _scope(uuid4())
    state = (
        SimpleNamespace(principal_active=member[0], membership_active=member[1]) if member else None
    )
    session = _session([uuid4()], state)
    require = AsyncMock()
    monkeypatch.setattr(privacy, "require_resources", require)
    with pytest.raises(BrainDeniedError, match="recipient is unavailable"):
        await privacy.recipients(cast(AsyncSession, session), scope, uuid4(), (uuid4(),), NOW)
    require.assert_not_awaited()


@pytest.mark.asyncio
async def test_every_recipient_must_pass_the_full_input_resource_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    company = uuid4()
    scope = _scope(company)
    principals = [uuid4(), uuid4()]
    resources = (uuid4(), uuid4())
    session = _session(principals, SimpleNamespace(principal_active=True, membership_active=True))
    grants = [_grant(company, None), _grant(company, None)]
    require = AsyncMock(side_effect=[(grants[0],), (grants[1],)])
    monkeypatch.setattr(privacy, "require_resources", require)
    result = await privacy.recipients(cast(AsyncSession, session), scope, uuid4(), resources, NOW)
    assert result == tuple(grants)
    assert require.await_count == 2
    for call, principal in zip(require.await_args_list, principals, strict=True):
        assert call.args[1].principal_id == principal
        assert call.args[1].company_id == company
        assert call.args[2:] == (resources, NOW)


@pytest.mark.asyncio
async def test_one_denied_recipient_rejects_the_whole_audience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    company = uuid4()
    scope = _scope(company)
    session = _session(
        [uuid4(), uuid4()], SimpleNamespace(principal_active=True, membership_active=True)
    )
    require = AsyncMock(side_effect=[(_grant(company, None),), BrainDeniedError("revoked")])
    monkeypatch.setattr(privacy, "require_resources", require)
    with pytest.raises(BrainDeniedError, match="revoked"):
        await privacy.recipients(cast(AsyncSession, session), scope, uuid4(), (uuid4(),), NOW)
    assert require.await_count == 2
