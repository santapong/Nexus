"""Fixed company-first FK indexes for the reviewed Brain schema; metadata only."""

from __future__ import annotations

from sqlalchemy import Index

from nexus.company.brain.model_base import BrainBase

# Static declarations generated/reviewed with the company008 schema, never caller input.
INDEX_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_brain_fk_3642bf8aa8168237", "company_brain_access_events", ("company_id", "owner_id")),
    ("ix_brain_fk_ec86acc99269961c", "company_brain_access_events", ("company_id", "principal_id")),
    ("ix_brain_fk_ad5a89ea05a41339", "company_brain_access_events", ("company_id", "resource_id")),
    (
        "ix_brain_fk_0a1aa54a8eff1560",
        "company_brain_artifact_revisions",
        ("company_id", "derivation_id"),
    ),
    (
        "ix_brain_fk_80f05897791c5d9c",
        "company_brain_artifact_revisions",
        ("company_id", "resource_id"),
    ),
    (
        "ix_brain_fk_5e5c1e09f931fb10",
        "company_brain_chunks",
        ("company_id", "parse_revision_id", "source_revision_id"),
    ),
    (
        "ix_brain_fk_e437c1addeebcd73",
        "company_brain_claim_evidence",
        ("company_id", "claim_revision_id"),
    ),
    ("ix_brain_fk_fd3253b2acd368d7", "company_brain_claim_evidence", ("company_id", "evidence_id")),
    (
        "ix_brain_fk_47332ff8be0cf371",
        "company_brain_claim_heads",
        ("company_id", "claim_id", "current_revision_id"),
    ),
    (
        "ix_brain_fk_84d70f3c484da11e",
        "company_brain_claim_link_evidence",
        ("company_id", "evidence_id"),
    ),
    (
        "ix_brain_fk_756305f81ea86ac0",
        "company_brain_claim_link_evidence",
        ("company_id", "link_id"),
    ),
    (
        "ix_brain_fk_ce781e6a1e8bd89b",
        "company_brain_claim_links",
        ("company_id", "object_revision_id"),
    ),
    ("ix_brain_fk_9bda65b06b02ae23", "company_brain_claim_links", ("company_id", "recorded_by")),
    (
        "ix_brain_fk_58497535d80970a7",
        "company_brain_claim_links",
        ("company_id", "subject_revision_id"),
    ),
    (
        "ix_brain_fk_f663acbf4192c370",
        "company_brain_claim_revisions",
        ("company_id", "resource_id"),
    ),
    (
        "ix_brain_fk_5061b12f202bab4a",
        "company_brain_derivation_evidence",
        ("company_id", "derivation_id"),
    ),
    (
        "ix_brain_fk_f006e149eaae0d79",
        "company_brain_derivation_evidence",
        ("company_id", "evidence_id"),
    ),
    (
        "ix_brain_fk_32b6e2660a2dcc56",
        "company_brain_derivation_sources",
        ("company_id", "derivation_id"),
    ),
    (
        "ix_brain_fk_89a44dc113f65842",
        "company_brain_derivation_sources",
        ("company_id", "source_revision_id"),
    ),
    (
        "ix_brain_fk_294a8f719997920e",
        "company_brain_derivations",
        ("company_id", "artifact_revision_id"),
    ),
    (
        "ix_brain_fk_ed855b780adc1d98",
        "company_brain_entities",
        ("company_id", "entity_id", "current_revision_id", "kind"),
    ),
    ("ix_brain_fk_f5d4afd8c3fad7df", "company_brain_entities", ("company_id", "resource_id")),
    (
        "ix_brain_fk_46e25269404eef1b",
        "company_brain_entity_evidence",
        ("company_id", "entity_revision_id"),
    ),
    (
        "ix_brain_fk_50f13b34af064a4a",
        "company_brain_entity_evidence",
        ("company_id", "evidence_id"),
    ),
    (
        "ix_brain_fk_77fd8e214e51d8dc",
        "company_brain_entity_revisions",
        ("company_id", "entity_id", "kind"),
    ),
    ("ix_brain_fk_c159690c86f3ea01", "company_brain_event_cursors", ("company_id",)),
    ("ix_brain_fk_419f85c1dd9e11a4", "company_brain_events", ("company_id", "action_id")),
    ("ix_brain_fk_828b12df4823ecc5", "company_brain_events", ("company_id", "resource_id")),
    ("ix_brain_fk_c65f02786fe0cf35", "company_brain_events", ("company_id", "source_revision_id")),
    (
        "ix_brain_fk_4fcf7b275dd77891",
        "company_brain_evidence",
        ("company_id", "chunk_id", "parse_revision_id", "source_revision_id"),
    ),
    (
        "ix_brain_fk_ce24af2f6dd05d5d",
        "company_brain_evidence",
        ("company_id", "parse_revision_id", "source_revision_id"),
    ),
    (
        "ix_brain_fk_324503ae4bbaa82a",
        "company_brain_evidence",
        ("company_id", "source_id", "source_revision_id"),
    ),
    (
        "ix_brain_fk_35c0399f58f5d246",
        "company_brain_evidence",
        ("company_id", "source_revision_id", "artifact_revision_id"),
    ),
    (
        "ix_brain_fk_ec4da53656aa9acc",
        "company_brain_parse_failures",
        ("company_id", "source_id", "source_revision_id"),
    ),
    (
        "ix_brain_fk_842c2e577372580f",
        "company_brain_relationship_evidence",
        ("company_id", "evidence_id"),
    ),
    (
        "ix_brain_fk_400c923cde0e66a9",
        "company_brain_relationship_evidence",
        ("company_id", "relationship_revision_id"),
    ),
    (
        "ix_brain_fk_a60f3d0fa02b352e",
        "company_brain_relationship_revisions",
        ("company_id", "object_id", "object_revision_id", "object_kind"),
    ),
    (
        "ix_brain_fk_4b86824081c5928e",
        "company_brain_relationship_revisions",
        ("company_id", "subject_id", "subject_revision_id", "subject_kind"),
    ),
    (
        "ix_brain_fk_171a763dbba8e7fc",
        "company_brain_resource_access",
        ("company_id", "principal_id"),
    ),
    (
        "ix_brain_fk_ba5123b70e5fd28d",
        "company_brain_resource_access",
        ("company_id", "resource_id"),
    ),
    ("ix_brain_fk_dd50f6598e292e83", "company_brain_resources", ("company_id",)),
    (
        "ix_brain_fk_0b065feb878e420d",
        "company_brain_source_heads",
        ("company_id", "source_id", "current_revision_id"),
    ),
    (
        "ix_brain_fk_6928ab31ad48bef6",
        "company_brain_source_revisions",
        ("company_id", "artifact_revision_id"),
    ),
    (
        "ix_brain_fk_90b270efede802ca",
        "company_brain_source_revisions",
        ("company_id", "derivation_id"),
    ),
    (
        "ix_brain_fk_3a54a748bc7ed500",
        "company_brain_source_revisions",
        ("company_id", "recorded_by"),
    ),
    ("ix_brain_fk_dba2f048cacb8ab0", "company_brain_sources", ("company_id", "recorded_by")),
    ("ix_brain_fk_ef585b6c0b22537c", "company_brain_sources", ("company_id", "resource_id")),
)


def register_indexes() -> None:
    """Describe query/FK indexes; only normal Alembic migration executes their DDL."""
    for name, table_name, columns in INDEX_SPECS:
        table = BrainBase.metadata.tables[table_name]
        if name not in {index.name for index in table.indexes}:
            Index(name, *(table.c[column] for column in columns))
