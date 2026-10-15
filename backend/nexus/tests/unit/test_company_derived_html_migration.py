"""Offline named-constraint/revision checks only; no mocked PostgreSQL execution proof."""

from collections.abc import Callable
from typing import cast

import pytest
from sqlalchemy import CheckConstraint, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Dialect
from sqlalchemy.schema import AddConstraint

from nexus.company.brain.source_models import BrainArtifactRevision


def test_named_artifact_constraint_describes_only_derived_html_extension() -> None:
    table = cast(Table, BrainArtifactRevision.__table__)
    checks = [row for row in table.constraints if row.name == "ck_brain_artifact_media"]
    assert len(checks) == 1 and isinstance(checks[0], CheckConstraint)
    ddl = str(
        AddConstraint(checks[0]).compile(dialect=cast(Callable[[], Dialect], postgresql.dialect)())
    )
    assert "text/html" in ddl
    assert "derivation_id IS NOT NULL" in ddl
    assert "'text/plain','text/markdown','application/json'" in ddl
    assert "text/html;" not in ddl and "image/svg+xml" not in ddl


def test_normal016_is_only_head_and_preserves_original008_bytes() -> None:
    import hashlib
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[3]
    config = Config(str(root / "alembic_company.ini"))
    config.set_main_option("script_location", str(root / "company_alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["company_016"]
    current = scripts.get_revision("company_016")
    assert current is not None and current.down_revision == "company_015"
    original = root / "company_alembic/versions/company_008_brain.py"
    assert hashlib.sha256(original.read_bytes()).hexdigest() == (
        "77b021bfa98ac0d532d8f528bd39586fd2bbd94673304b86b51a8dd167827ad7"
    )


def test_upgrade_and_downgrade_compile_only_named_constraint_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from io import StringIO

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from company_alembic.versions import company_016_derived_html_artifacts as migration

    for direction, expression in (
        ("upgrade", migration.DERIVED_HTML_MEDIA),
        ("downgrade", migration.ORIGINAL_MEDIA),
    ):
        output = StringIO()
        context = MigrationContext.configure(
            dialect_name="postgresql",
            opts={"as_sql": True, "output_buffer": output, "transactional_ddl": True},
        )
        monkeypatch.setattr(migration, "op", Operations(context))
        with context.begin_transaction():
            getattr(migration, direction)()
        ddl = output.getvalue()
        assert "BEGIN;" in ddl and "COMMIT;" in ddl
        assert ddl.count("DROP CONSTRAINT ck_brain_artifact_media") == 1
        assert ddl.count("ADD CONSTRAINT ck_brain_artifact_media") == 1
        assert expression in ddl and "NOT VALID" not in ddl
        assert all(
            token not in ddl.upper()
            for token in ("DELETE ", "TRUNCATE ", "UPDATE ", "CREATE TABLE", "ROW LEVEL", "GRANT ")
        )
        if direction == "downgrade":
            assert "text/html" not in ddl
        else:
            table = cast(Table, BrainArtifactRevision.__table__)
            check = next(row for row in table.constraints if row.name == migration.CONSTRAINT)
            assert isinstance(check, CheckConstraint) and str(check.sqltext) == expression


def test_html_still_uses_deferred_same_company_derivation_and_unchanged_byte_hash_checks() -> None:
    from sqlalchemy import ForeignKeyConstraint

    from nexus.company.brain import models

    table = cast(Table, models.BrainArtifactRevision.__table__)
    foreign = next(row for row in table.constraints if row.name == "fk_brain_artifact_derivation")
    assert isinstance(foreign, ForeignKeyConstraint)
    assert foreign.deferrable is True and foreign.initially == "DEFERRED"
    assert tuple(element.parent.name for element in foreign.elements) == (
        "company_id",
        "derivation_id",
    )
    assert tuple(element.target_fullname for element in foreign.elements) == (
        "company_brain_derivations.company_id",
        "company_brain_derivations.derivation_id",
    )
    checks = {
        row.name: str(row.sqltext) for row in table.constraints if isinstance(row, CheckConstraint)
    }
    assert (
        checks["ck_brain_artifact_bytes"]
        == "byte_length = octet_length(raw_text) AND byte_length BETWEEN 1 AND 2097152"
    )
    assert checks["ck_brain_artifact_hash"] == "sha256 ~ '^[0-9a-f]{64}$'"
