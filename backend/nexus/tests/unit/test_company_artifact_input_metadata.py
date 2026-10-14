"""Native immutable company-scoped artifact/resource lineage declarations."""

from typing import cast

from sqlalchemy import Table, Uuid

from nexus.company.brain.artifact_input_models import BrainArtifactInput, BrainArtifactResourceInput
from nexus.company.brain.source_models import BrainArtifactRevision


def test_artifact_inputs_use_native_company_keys_and_fk_coverage() -> None:
    for model in (BrainArtifactInput, BrainArtifactResourceInput):
        table = cast(Table, model.__table__)
        assert next(iter(table.primary_key.columns)).name == "company_id"
        assert isinstance(table.c.company_id.type, Uuid)
        indexes = [
            tuple(table.primary_key.columns.keys()),
            *(tuple(index.columns.keys()) for index in table.indexes),
        ]
        for key in table.foreign_key_constraints:
            columns = tuple(key.columns.keys())
            assert any(prefix[: len(columns)] == columns for prefix in indexes), key.name
            assert all(element.column.table.name.startswith("company_") for element in key.elements)
    assert cast(Table, BrainArtifactRevision.__table__).c.data_classification.nullable
