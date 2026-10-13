"""Every management FK needs an actual covering metadata index before normal migration."""

from sqlalchemy import UniqueConstraint

from nexus.company.management.models import ManagementBase


def test_every_management_foreign_key_has_a_covering_index_prefix() -> None:
    for table in ManagementBase.metadata.tables.values():
        prefixes = {tuple(table.primary_key.columns.keys())}
        prefixes.update(tuple(index.columns.keys()) for index in table.indexes)
        prefixes.update(
            tuple(constraint.columns.keys())
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        )
        for foreign in table.foreign_key_constraints:
            columns = tuple(foreign.columns.keys())
            assert any(prefix[: len(columns)] == columns for prefix in prefixes), (
                table.name,
                foreign.name,
                columns,
            )
