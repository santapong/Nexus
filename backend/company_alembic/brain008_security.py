"""Frozen company008 security DDL; no evolving ORM or application imports."""

import sqlalchemy as sa

from alembic import op

TABLES = (
    "company_brain_access_events",
    "company_brain_artifact_revisions",
    "company_brain_chunks",
    "company_brain_claim_evidence",
    "company_brain_claim_heads",
    "company_brain_claim_link_evidence",
    "company_brain_claim_links",
    "company_brain_claim_revisions",
    "company_brain_derivation_evidence",
    "company_brain_derivation_sources",
    "company_brain_derivations",
    "company_brain_entities",
    "company_brain_entity_evidence",
    "company_brain_entity_revisions",
    "company_brain_event_cursors",
    "company_brain_events",
    "company_brain_evidence",
    "company_brain_parse_failures",
    "company_brain_parse_revisions",
    "company_brain_relationship_evidence",
    "company_brain_relationship_revisions",
    "company_brain_resource_access",
    "company_brain_resources",
    "company_brain_source_heads",
    "company_brain_source_revisions",
    "company_brain_sources",
)
MUTABLE = (
    "company_brain_resources",
    "company_brain_resource_access",
    "company_brain_source_heads",
    "company_brain_entities",
    "company_brain_claim_heads",
    "company_brain_event_cursors",
)


def install_security() -> None:
    """Enable forced tenant policies and immutable history before company008 commits."""
    for table in TABLES:
        for command in (
            "ALTER TABLE %(table)s ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE %(table)s FORCE ROW LEVEL SECURITY",
            "CREATE POLICY company_scope ON %(table)s USING "
            "(company_id = nullif(current_setting('nexus.company_id', true), '')::uuid) "
            "WITH CHECK (company_id = nullif(current_setting('nexus.company_id', true), '')::uuid)",
        ):
            op.execute(sa.schema.DDL(command, context={"table": table}))
    op.execute("""
        CREATE FUNCTION nexus_brain_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Brain history is immutable'; END; $$
    """)
    for table in TABLES:
        if table not in MUTABLE:
            op.execute(
                sa.schema.DDL(
                    "CREATE TRIGGER brain_immutable BEFORE UPDATE OR DELETE ON %(table)s "
                    "FOR EACH ROW EXECUTE FUNCTION nexus_brain_immutable()",
                    context={"table": table},
                )
            )
    _mutable_guards()
    _parse_pair_guard()


def _mutable_guards() -> None:
    """Current pointers can advance; tenant/identity and lineage cannot be replaced."""
    op.execute("""
        CREATE FUNCTION nexus_brain_current_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE old_row jsonb; new_row jsonb;
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Brain current state cannot be deleted'; END IF;
          old_row := to_jsonb(OLD); new_row := to_jsonb(NEW);
          IF NEW.company_id IS DISTINCT FROM OLD.company_id THEN
            RAISE EXCEPTION 'Brain company identity is immutable';
          END IF;
          IF TG_TABLE_NAME = 'company_brain_resources' THEN
            IF (new_row - ARRAY['active','acl_generation','updated_at']) IS DISTINCT FROM
               (old_row - ARRAY['active','acl_generation','updated_at']) OR
               NEW.acl_generation < OLD.acl_generation OR
               NEW.acl_generation > OLD.acl_generation + 1 OR
               (NEW.active IS DISTINCT FROM OLD.active AND
                NEW.acl_generation <> OLD.acl_generation + 1) THEN
              RAISE EXCEPTION 'Brain resource binding or generation is invalid';
            END IF;
          ELSIF TG_TABLE_NAME = 'company_brain_resource_access' THEN
            IF (new_row - ARRAY['active','generation','expires_at']) IS DISTINCT FROM
               (old_row - ARRAY['active','generation','expires_at']) OR
               NEW.generation < OLD.generation OR
               ((NEW.active, NEW.expires_at) IS DISTINCT FROM (OLD.active, OLD.expires_at)
                AND NEW.generation <= OLD.generation) THEN
              RAISE EXCEPTION 'Brain grant binding or generation is invalid';
            END IF;
          ELSE
            PERFORM nexus_brain_head_check(TG_TABLE_NAME, old_row, new_row);
          END IF;
          RETURN NEW;
        END; $$
    """)
    _head_check()
    for table in MUTABLE:
        op.execute(
            sa.schema.DDL(
                "CREATE TRIGGER brain_current BEFORE UPDATE OR DELETE ON %(table)s "
                "FOR EACH ROW EXECUTE FUNCTION nexus_brain_current_guard()",
                context={"table": table},
            )
        )


def _head_check() -> None:
    """Source generations/cursors are monotone; other current pointers retain identity."""
    op.execute("""
        CREATE FUNCTION nexus_brain_head_check(kind text, old_row jsonb, new_row jsonb)
        RETURNS void LANGUAGE plpgsql AS $$
        BEGIN
          IF kind = 'company_brain_source_heads' THEN
            IF (new_row - ARRAY['current_revision_id','generation','observed_at','fresh_until',
                               'availability']) IS DISTINCT FROM
               (old_row - ARRAY['current_revision_id','generation','observed_at','fresh_until',
                               'availability']) OR
               (new_row->>'generation')::bigint < (old_row->>'generation')::bigint OR
               (new_row->>'generation')::bigint > (old_row->>'generation')::bigint + 1 OR
               ((new_row->>'current_revision_id',new_row->>'availability') IS DISTINCT FROM
                (old_row->>'current_revision_id',old_row->>'availability') AND
                (new_row->>'generation')::bigint <> (old_row->>'generation')::bigint + 1) THEN
              RAISE EXCEPTION 'Brain source pointer or generation is invalid';
            END IF;
          ELSIF kind IN ('company_brain_entities','company_brain_claim_heads') THEN
            IF (new_row - 'current_revision_id') IS DISTINCT FROM (old_row - 'current_revision_id')
            THEN RAISE EXCEPTION 'Brain entity or claim identity is immutable'; END IF;
          ELSIF kind = 'company_brain_event_cursors' THEN
            IF (new_row - 'last_sequence') IS DISTINCT FROM (old_row - 'last_sequence') OR
               (new_row->>'last_sequence')::bigint < (old_row->>'last_sequence')::bigint THEN
              RAISE EXCEPTION 'Brain consumer identity or cursor is invalid';
            END IF;
          ELSE RAISE EXCEPTION 'Unknown Brain current-state table';
          END IF;
        END; $$
    """)


def _parse_pair_guard() -> None:
    """Serialize both parse outcomes by the company mutex; one immutable outcome per recipe."""
    op.execute("""
        CREATE FUNCTION nexus_brain_parse_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          PERFORM 1 FROM company_controls WHERE company_id = NEW.company_id FOR UPDATE;
          IF NOT FOUND THEN RAISE EXCEPTION 'Brain company scope is unavailable'; END IF;
          IF TG_TABLE_NAME = 'company_brain_parse_revisions' THEN
            IF EXISTS (SELECT 1 FROM company_brain_parse_failures
                WHERE company_id = NEW.company_id AND source_revision_id = NEW.source_revision_id
                AND parser_version = NEW.parser_version AND chunker_version = NEW.chunker_version)
            THEN RAISE EXCEPTION 'Brain parse recipe already has a failure'; END IF;
          ELSE
            IF EXISTS (SELECT 1 FROM company_brain_parse_revisions
                WHERE company_id = NEW.company_id AND source_revision_id = NEW.source_revision_id
                AND parser_version = NEW.parser_version AND chunker_version = NEW.chunker_version)
            THEN RAISE EXCEPTION 'Brain parse recipe already has a successful parse'; END IF;
          END IF;
          RETURN NEW;
        END; $$
    """)
    for table in ("company_brain_parse_revisions", "company_brain_parse_failures"):
        op.execute(
            sa.schema.DDL(
                "CREATE TRIGGER brain_parse_outcome BEFORE INSERT ON %(table)s "
                "FOR EACH ROW EXECUTE FUNCTION nexus_brain_parse_guard()",
                context={"table": table},
            )
        )


def remove_functions() -> None:
    """Called after all company008 tables/triggers are normally downgraded."""
    op.execute("DROP FUNCTION nexus_brain_parse_guard()")
    op.execute("DROP FUNCTION nexus_brain_current_guard()")
    op.execute("DROP FUNCTION nexus_brain_head_check(text,jsonb,jsonb)")
    op.execute("DROP FUNCTION nexus_brain_immutable()")
