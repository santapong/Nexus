"""Normal migration SQL/DTO checks only; no database migration/rollback proof."""

import importlib.util
import io
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import CheckConstraint, Table

from nexus.company.brain.claims import DerivationRecord
from nexus.company.brain.derivation_models import BrainDerivation
from nexus.tests.unit.test_coding_prepared_contracts import encoded_case


@pytest.mark.parametrize("kind", ["model_origin", "code_patch"])
def test_genuine_new_derivation_kinds_have_dto_and_named_sql_constraints(kind: str) -> None:
    header, _, _ = encoded_case()
    value = DerivationRecord.model_validate_json(
        '{"company_id":"'
        + str(header.company_id)
        + '","derivation_id":"'
        + str(header.action_id)
        + '","artifact":'
        + header.body.model_dump_json()
        + ',"recipe_version":"coding-publication-v1",'
        '"kind":"'
        + kind
        + '","contributors":['
        + header.code_sources[0].source.model_dump_json()
        + '],"recorded_at":"2026-10-16T12:00:00Z"}'
    )
    assert value.kind == kind
    constraint = next(
        row
        for row in cast(Table, BrainDerivation.__table__).constraints
        if row.name == "ck_brain_derivation_kind"
    )
    assert "'" + kind + "'" in str(cast(CheckConstraint, constraint).sqltext)


def migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[3]
        / "company_alembic/versions/company_017_coding_publication.py"
    )
    spec = importlib.util.spec_from_file_location("fixture_company017", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_company017_is_additive_normal_named_check_ddl_without_data_rewrite() -> None:
    module = migration()
    assert module.revision == "company_017" and module.down_revision == "company_016"
    for operation, expected in (("upgrade", True), ("downgrade", False)):
        output = io.StringIO()
        context = MigrationContext.configure(
            dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
        )
        with Operations.context(context):
            getattr(module, operation)()
        sql = output.getvalue()
        assert "DROP CONSTRAINT ck_brain_derivation_kind" in sql
        assert "ADD CONSTRAINT ck_brain_derivation_kind CHECK" in sql
        assert ("'code_patch'" in sql) is expected and ("'model_origin'" in sql) is expected
        assert not any(
            word in sql.upper() for word in ("DELETE ", "UPDATE ", "TRUNCATE ", "DROP TABLE")
        )
        assert all(
            "'" + kind + "'" in sql
            for kind in ("summary", "chart", "presentation", "context", "embedding_derived_text")
        )
        assert context.impl.transactional_ddl is True
