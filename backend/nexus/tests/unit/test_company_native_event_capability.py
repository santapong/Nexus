"""Closed profile compatibility uses real capability code with SQL reply stubs only."""

from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.native_event_capability import native_event_capability
from nexus.company.brain.native_event_schema import NATIVE_EVENT_FIELDS
from nexus.company.brain.scope_support import BrainDeniedError


class Columns:
    """Only the physical column query response is replaced in this unit scope."""

    def __init__(self, names: tuple[str, ...]) -> None:
        self.names = names

    def scalars(self) -> tuple[str, ...]:
        return self.names


class Replies:
    """Retain query order; this stub establishes no PostgreSQL capability."""

    def __init__(
        self, names: tuple[str, ...], version: object, table: object = "qualified"
    ) -> None:
        self.names = names
        self.values = iter((table, version))
        self.queries: list[str] = []

    async def execute(self, statement: object) -> Columns:
        self.queries.append(str(statement))
        return Columns(self.names)

    async def scalar(self, statement: object) -> object:
        self.queries.append(str(statement))
        return next(self.values)


@pytest.mark.parametrize("version", ["company_015", "company_016"])
async def test_complete_native_columns_require_a_known_exact_profile(version: str) -> None:
    replies = Replies(tuple(NATIVE_EVENT_FIELDS), version)
    assert await native_event_capability(cast(AsyncSession, replies))
    assert len(replies.queries) == 3


@pytest.mark.parametrize("version", [None, 16, "company_014", "company_017", "company_016-extra"])
async def test_unknown_profile_does_not_inherit_native_event_capability(version: object) -> None:
    replies = Replies(tuple(NATIVE_EVENT_FIELDS), version)
    with pytest.raises(BrainDeniedError, match="profile version"):
        await native_event_capability(cast(AsyncSession, replies))


@pytest.mark.parametrize("version", ["company_015", "company_016"])
async def test_missing_native_column_denies_even_a_known_profile(version: str) -> None:
    replies = Replies(tuple(NATIVE_EVENT_FIELDS)[1:], version)
    with pytest.raises(BrainDeniedError, match="incomplete"):
        await native_event_capability(cast(AsyncSession, replies))
    assert len(replies.queries) == 1


async def test_legacy_column_shape_uses_only_legacy_sql() -> None:
    replies = Replies(("company_id", "event_id"), "company_014")
    assert not await native_event_capability(cast(AsyncSession, replies))
    assert len(replies.queries) == 1


async def test_complete_columns_without_profile_table_do_not_qualify() -> None:
    replies = Replies(tuple(NATIVE_EVENT_FIELDS), "company_016", table=None)
    with pytest.raises(BrainDeniedError, match="profile is not qualified"):
        await native_event_capability(cast(AsyncSession, replies))
    assert len(replies.queries) == 2
