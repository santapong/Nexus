"""Uninstalled metadata compilation does not claim migration/RLS or M2 runtime proof."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Uuid
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.engine import Dialect
from sqlalchemy.schema import CreateTable

from nexus.company.brain.models import BrainBase, BrainClaimRevision, BrainEvidence

_DIALECT = cast(Callable[[], Dialect], PGDialect)


def test_every_table_and_revision_fk_preserves_native_company_scope() -> None:
    assert len(BrainBase.metadata.tables) == 28  # Additive012 retains all26 prior Brain tables.
    for table in BrainBase.metadata.sorted_tables:
        assert isinstance(table.c.company_id.type, Uuid)
        assert table.c.company_id.primary_key
        assert "UUID" in str(CreateTable(table).compile(dialect=_DIALECT()))
        for constraint in table.constraints:
            if isinstance(constraint, ForeignKeyConstraint):
                if isinstance(constraint.name, str) and constraint.name.startswith("fk_brain_"):
                    assert "company_id" in constraint.column_keys
                for element in constraint.elements:
                    if isinstance(element.parent.type, Uuid):
                        assert isinstance(element.column.type, Uuid)


def test_same_company_does_not_allow_evidence_from_another_source_artifact_parse() -> None:
    table = BrainBase.metadata.tables[BrainEvidence.__tablename__]
    keys = {constraint.name: constraint.column_keys for constraint in table.foreign_key_constraints}
    assert keys["fk_brain_evidence_source"] == ["company_id", "source_id", "source_revision_id"]
    assert keys["fk_brain_evidence_artifact"] == [
        "company_id",
        "source_revision_id",
        "artifact_revision_id",
    ]
    assert keys["fk_brain_evidence_chunk"] == [
        "company_id",
        "chunk_id",
        "parse_revision_id",
        "source_revision_id",
    ]


def test_raw_uuids_cannot_mint_a_persisted_verified_outcome() -> None:
    table = BrainBase.metadata.tables[BrainClaimRevision.__tablename__]
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "verified_outcome" in checks["ck_brain_claim_kind"]
    assert checks["ck_company_brain_verified_outcome_disabled"] == "kind <> 'verified_outcome'"
    assert (
        checks["ck_brain_claim_no_uuid_promotion"]
        == "verification_id IS NULL AND receipt_id IS NULL"
    )


def test_brain_primary_keys_preserve_company_first_scoped_lookup_binding() -> None:
    """Runtime composite lookups must not silently swap tenant and object identifiers."""
    from nexus.company.brain.models import BrainBase

    for table in BrainBase.metadata.tables.values():
        assert next(iter(table.primary_key.columns)).name == "company_id"
