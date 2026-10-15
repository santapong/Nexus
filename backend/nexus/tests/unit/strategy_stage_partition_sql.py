"""Small predicate-faithful SQL response fixture; never a database or passing gate stub."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BindParameter, BooleanClauseList, Grouping, Null, TextClause

if TYPE_CHECKING:
    from nexus.tests.unit.strategy_stage_partition_fixture import Stage


class Queries:
    """Interpret only the SELECT shapes used by the actual stage/current-binding helpers."""

    def __init__(self, stage: Stage) -> None:
        self.stage = stage
        self.session = MagicMock(spec=AsyncSession)
        self.session.in_transaction.return_value = True
        self.session.scalar = AsyncMock(side_effect=self.scalar)
        self.session.scalars = AsyncMock(side_effect=self.scalars)
        self.session.get = AsyncMock(side_effect=self.get)
        for method in ("add", "add_all", "flush", "commit", "begin", "execute"):
            setattr(
                self.session, method, MagicMock(side_effect=AssertionError("No writes: " + method))
            )

    def value(self, expression: Any, row: Any) -> Any:
        # SQLAlchemy expression nodes are runtime-generic; unsupported operations fail loudly.
        if isinstance(expression, BindParameter):
            return expression.value
        if isinstance(expression, Null):
            return None
        table = expression.table.name
        if table == row.__table__.name:
            return getattr(row, expression.key)
        joined = [
            candidate
            for candidate in cast(list[Any], self.stage.all_rows())
            if candidate.__table__.name == table
            and candidate.company_id == row.company_id
            and candidate.plan_revision_id == row.plan_revision_id
        ]
        assert len(joined) <= 1
        return getattr(joined[0], expression.key) if joined else None

    def matches(self, expression: Any, row: Any) -> bool:
        if isinstance(expression, Grouping):
            return self.matches(expression.element, row)
        if isinstance(expression, BooleanClauseList):
            values = [self.matches(part, row) for part in expression.clauses]
            assert expression.operator in {operators.and_, operators.or_}
            return all(values) if expression.operator is operators.and_ else any(values)
        left, right = self.value(expression.left, row), self.value(expression.right, row)
        if expression.operator is operators.eq:
            return bool(left == right)
        if expression.operator is operators.in_op:
            return left in right
        raise AssertionError("Unsupported SQL predicate")

    def selected(self, statement: Select[Any]) -> list[Any]:
        model = statement.column_descriptions[0]["entity"]
        rows = [row for row in self.stage.all_rows() if type(row) is model]
        rows = [row for row in rows if all(self.matches(w, row) for w in statement._where_criteria)]
        if model.__name__ == "ManagementPlanTask":
            self.stage.binding_queries += 1
        for order in reversed(tuple(statement._order_by_clauses)):
            reverse = getattr(order, "modifier", None) is operators.desc_op
            column = order.element if hasattr(order, "element") else order
            rows.sort(key=lambda row: self.value(column, row), reverse=reverse)
        if statement._limit_clause is not None:
            rows = rows[: statement._limit_clause.value]
        return rows

    async def scalar(self, statement: Any) -> Any:
        if isinstance(statement, TextClause):
            assert "rolsuper OR rolbypassrls" in statement.text
            return self.stage.privileged
        if statement.column_descriptions[0].get("entity") is None:
            assert "clock_timestamp()" in str(statement)
            return self.stage.clock
        rows = self.selected(statement)
        return rows[0] if rows else None

    async def scalars(self, statement: Select[Any]) -> MagicMock:
        rows = self.selected(statement)
        if (
            statement.column_descriptions[0]["entity"].__name__ == "RegisteredWork"
            and self.stage.expire_at_family
        ):
            self.stage.clock = self.stage.proof.initial.sources.credential.expires_at
        result = MagicMock()
        result.all.return_value = rows
        return result

    async def get(self, model: type[object], key: object) -> object | None:
        return self.stage.stored.get((model, key))
