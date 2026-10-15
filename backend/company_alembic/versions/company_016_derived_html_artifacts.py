"""Allow exact derived HTML artifact bytes; downgrade retains incompatible evidence by failing."""

from alembic import op

revision = "company_016"
down_revision = "company_015"
branch_labels = None
depends_on = None

TABLE = "company_brain_artifact_revisions"
CONSTRAINT = "ck_brain_artifact_media"
ORIGINAL_MEDIA = "media_type IN ('text/plain','text/markdown','application/json')"
DERIVED_HTML_MEDIA = ORIGINAL_MEDIA + " OR (media_type = 'text/html' AND derivation_id IS NOT NULL)"


def upgrade() -> None:
    """Keep the original formats and all same-company deferred provenance FKs unchanged."""
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, DERIVED_HTML_MEDIA)


def downgrade() -> None:
    """Normal transactional DDL rejects any retained HTML; it never deletes or rewrites rows."""
    # CHECK validation examines existing table data even when an operator cannot SELECT RLS rows.
    # If HTML remains, ADD fails and PostgreSQL rolls back this DROP and the version transition.
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, ORIGINAL_MEDIA)
