"""A2A token PBKDF2 hashing — per-token salt + algorithm marker.

Revision ID: 014
Revises: 011
Create Date: 2026-05-21

Changes:
- Widen a2a_tokens.token_hash from VARCHAR(64) to VARCHAR(128). PBKDF2-HMAC-SHA256
  yields a 32-byte digest (64 hex chars), same as SHA-256, but the wider column
  leaves headroom for future algorithm upgrades.
- Add a2a_tokens.salt (BYTEA, nullable). Stores the per-token 16-byte salt used
  with PBKDF2. NULL for legacy sha256 rows.
- Add a2a_tokens.hash_algo (VARCHAR(32), NOT NULL, default 'sha256'). Marks the
  hashing algorithm. New tokens use 'pbkdf2_sha256'. Existing rows keep 'sha256'
  and must be rotated by their owners (we cannot rehash without the plaintext).

Numbering note: F5 is creating 011_audit_perf_indexes.py (revision "011") and F11
may add a partitioning migration. The existing on-disk head is 011, so this
revision down-revisions from "011" and uses "014" to leave slack for parallel
work on 012/013.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "014"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add salt + hash_algo to a2a_tokens and widen token_hash."""
    op.alter_column(
        "a2a_tokens",
        "token_hash",
        existing_type=sa.String(64),
        type_=sa.String(128),
        existing_nullable=False,
    )
    op.add_column(
        "a2a_tokens",
        sa.Column("salt", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "a2a_tokens",
        sa.Column(
            "hash_algo",
            sa.String(32),
            nullable=False,
            server_default="sha256",
        ),
    )


def downgrade() -> None:
    """Reverse: drop salt + hash_algo, narrow token_hash back to VARCHAR(64)."""
    op.drop_column("a2a_tokens", "hash_algo")
    op.drop_column("a2a_tokens", "salt")
    op.alter_column(
        "a2a_tokens",
        "token_hash",
        existing_type=sa.String(128),
        type_=sa.String(64),
        existing_nullable=False,
    )
