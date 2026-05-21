"""Encrypt previously-plaintext OAuth tokens at rest (Fernet).

Revision ID: 012
Revises: 011
Create Date: 2026-05-21

Background
==========
The audit found `oauth_accounts.access_token_encrypted` and
`oauth_accounts.refresh_token_encrypted` storing **raw** OAuth tokens
despite their column names. Application code now wraps writes/reads in
`nexus.api.auth.encrypt_token` / `decrypt_token` (Fernet, keyed off
`NEXUS_ENCRYPTION_KEY`).

This migration backfills the table by re-encrypting any rows whose
contents are not already valid Fernet ciphertext, so existing rows can
be decrypted by the new application code.

Behavior
========
- Requires `NEXUS_ENCRYPTION_KEY` to be set in the environment.
- Iterates every row in `oauth_accounts`, attempts to decrypt with the
  configured Fernet key, and on `InvalidToken` (i.e. row is still
  plaintext from before this migration) re-writes it as ciphertext.
- Rows whose plaintext is empty/NULL are left untouched.
- If `NEXUS_ENCRYPTION_KEY` is unset the migration logs a warning and
  exits as a no-op so fresh dev environments without OAuth data can
  still upgrade. Production deployments must set the key first.

Downgrade
=========
Decrypts the columns back to plaintext (only useful if rolling back the
application code, which is not recommended). Same key requirement.

Note: the columns are already `TEXT` and easily fit Fernet ciphertext
(typically ~200 chars for a short access token), so no type change is
needed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _load_fernet() -> object | None:
    """Return a Fernet keyed off NEXUS_ENCRYPTION_KEY, or None if missing."""
    import os

    key = os.environ.get("NEXUS_ENCRYPTION_KEY", "").strip()
    if not key:
        print(  # noqa: T201 — alembic prints are fine
            "WARNING: NEXUS_ENCRYPTION_KEY not set; "
            "skipping OAuth token backfill. Set the key and re-run "
            "this migration to encrypt existing rows."
        )
        return None
    from cryptography.fernet import Fernet

    return Fernet(key.encode())


def upgrade() -> None:
    fernet = _load_fernet()
    if fernet is None:
        return

    from cryptography.fernet import InvalidToken

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, access_token_encrypted, refresh_token_encrypted FROM oauth_accounts")
    ).fetchall()

    updated = 0
    for row in rows:
        row_id, access_value, refresh_value = row

        new_access = access_value
        if access_value:
            try:
                fernet.decrypt(access_value.encode())  # already encrypted
            except (InvalidToken, ValueError):
                new_access = fernet.encrypt(access_value.encode()).decode()

        new_refresh = refresh_value
        if refresh_value:
            try:
                fernet.decrypt(refresh_value.encode())
            except (InvalidToken, ValueError):
                new_refresh = fernet.encrypt(refresh_value.encode()).decode()

        if new_access != access_value or new_refresh != refresh_value:
            bind.execute(
                sa.text(
                    "UPDATE oauth_accounts "
                    "SET access_token_encrypted = :acc, "
                    "    refresh_token_encrypted = :ref "
                    "WHERE id = :id"
                ),
                {"acc": new_access, "ref": new_refresh, "id": row_id},
            )
            updated += 1

    print(f"oauth_accounts: encrypted {updated} row(s)")  # noqa: T201


def downgrade() -> None:
    """Decrypt OAuth tokens back to plaintext (NOT recommended)."""
    import contextlib

    fernet = _load_fernet()
    if fernet is None:
        return

    from cryptography.fernet import InvalidToken

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, access_token_encrypted, refresh_token_encrypted FROM oauth_accounts")
    ).fetchall()

    for row in rows:
        row_id, access_value, refresh_value = row

        new_access = access_value
        if access_value:
            with contextlib.suppress(InvalidToken, ValueError):
                new_access = fernet.decrypt(access_value.encode()).decode()

        new_refresh = refresh_value
        if refresh_value:
            with contextlib.suppress(InvalidToken, ValueError):
                new_refresh = fernet.decrypt(refresh_value.encode()).decode()

        if new_access != access_value or new_refresh != refresh_value:
            bind.execute(
                sa.text(
                    "UPDATE oauth_accounts "
                    "SET access_token_encrypted = :acc, "
                    "    refresh_token_encrypted = :ref "
                    "WHERE id = :id"
                ),
                {"acc": new_access, "ref": new_refresh, "id": row_id},
            )
