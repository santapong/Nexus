"""Truthful model-origin/code-patch derivations; retained evidence prevents downgrade."""

from alembic import op

revision = "company_017"
down_revision = "company_016"
branch_labels = None
depends_on = None

TABLE = "company_brain_derivations"
CONSTRAINT = "ck_brain_derivation_kind"
ORIGINAL = "kind IN ('summary','chart','presentation','context','embedding_derived_text')"
CODING = (
    "kind IN ('summary','chart','presentation','context','embedding_derived_text',"
    "'model_origin','code_patch')"
)


def upgrade() -> None:
    """Add only the closed kinds; no source rows, RLS, grants, or triggers change."""
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, CODING)


def downgrade() -> None:
    """Retained new-kind rows make CHECK validation fail and transactional DDL roll back."""
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, ORIGINAL)
