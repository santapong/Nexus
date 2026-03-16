"""A2A Token management API — CRUD for external agent bearer tokens.

Endpoints for creating, listing, revoking, and rotating A2A tokens.
Tokens are stored in the a2a_tokens table with SHA-256 hash.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime

import structlog
from litestar import Controller, delete, get, post
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import A2ATokenRecord
from nexus.gateway.auth import (
    _hash_token,
    create_token,
    invalidate_cache,
    revoke_token,
)

logger = structlog.get_logger()


# ─── Request / Response models ────────────────────────────────────────────────


class CreateTokenRequest(BaseModel):
    """Request body for creating a new A2A token."""

    name: str
    allowed_skills: list[str] = ["*"]
    rate_limit_rpm: int = 60
    expires_in_hours: float | None = None


class CreateTokenResponse(BaseModel):
    """Response with the raw token — shown only once."""

    id: str
    name: str
    raw_token: str
    allowed_skills: list[str]
    rate_limit_rpm: int
    expires_at: str | None


class TokenInfo(BaseModel):
    """Public token info (no raw token or full hash)."""

    id: str
    name: str
    hash_prefix: str
    allowed_skills: list[str]
    rate_limit_rpm: int
    is_revoked: bool
    created_at: str
    expires_at: str | None
    last_used_at: str | None


class TokenListResponse(BaseModel):
    """List of tokens."""

    tokens: list[TokenInfo]
    total: int


class RotateTokenResponse(BaseModel):
    """Response after rotating a token."""

    old_token_id: str
    old_revoked: bool
    new_token: CreateTokenResponse


# ─── Controller ───────────────────────────────────────────────────────────────


class A2ATokenController(Controller):
    """CRUD endpoints for A2A bearer tokens."""

    path = "/a2a-tokens"

    @post("/")
    async def create(
        self,
        data: CreateTokenRequest,
        db_session: AsyncSession,
    ) -> CreateTokenResponse:
        """Create a new A2A bearer token.

        Generates a cryptographically secure random token, stores the
        SHA-256 hash in the database, and returns the raw token once.

        Args:
            data: Token configuration.
            db_session: Async database session.

        Returns:
            CreateTokenResponse with the raw token (shown only once).
        """
        raw_token = f"nexus-a2a-{secrets.token_urlsafe(32)}"

        expires_at = None
        if data.expires_in_hours is not None:
            from datetime import timedelta

            expires_at = datetime.now(UTC) + timedelta(
                hours=data.expires_in_hours
            )

        record = await create_token(
            raw_token=raw_token,
            name=data.name,
            allowed_skills=data.allowed_skills,
            rate_limit_rpm=data.rate_limit_rpm,
            expires_at=expires_at,
            db_session=db_session,
        )

        return CreateTokenResponse(
            id=str(record.id),
            name=record.name,
            raw_token=raw_token,
            allowed_skills=record.allowed_skills,
            rate_limit_rpm=record.rate_limit_rpm,
            expires_at=str(record.expires_at) if record.expires_at else None,
        )

    @get("/")
    async def list_tokens(
        self,
        db_session: AsyncSession,
    ) -> TokenListResponse:
        """List all A2A tokens (without revealing the full hash).

        Args:
            db_session: Async database session.

        Returns:
            TokenListResponse with token metadata.
        """
        stmt = select(A2ATokenRecord).order_by(
            A2ATokenRecord.created_at.desc()
        )
        result = await db_session.execute(stmt)
        records = result.scalars().all()

        tokens = [
            TokenInfo(
                id=str(r.id),
                name=r.name,
                hash_prefix=r.token_hash[:8] + "...",
                allowed_skills=r.allowed_skills,
                rate_limit_rpm=r.rate_limit_rpm,
                is_revoked=r.is_revoked,
                created_at=str(r.created_at),
                expires_at=str(r.expires_at) if r.expires_at else None,
                last_used_at=(
                    str(r.last_used_at) if r.last_used_at else None
                ),
            )
            for r in records
        ]

        return TokenListResponse(tokens=tokens, total=len(tokens))

    @delete("/{token_id:str}")
    async def revoke(
        self,
        token_id: str,
        db_session: AsyncSession,
    ) -> dict[str, object]:
        """Revoke an A2A token.

        Args:
            token_id: UUID of the token record.
            db_session: Async database session.

        Returns:
            Confirmation dict.
        """
        was_revoked = await revoke_token(token_id, db_session=db_session)
        if not was_revoked:
            return {"error": "Token not found", "id": token_id}
        return {"id": token_id, "revoked": True}

    @post("/{token_id:str}/rotate")
    async def rotate(
        self,
        token_id: str,
        db_session: AsyncSession,
    ) -> RotateTokenResponse | dict[str, str]:
        """Rotate a token — revoke the old one and issue a new one.

        The new token inherits the old token's name, skills, and RPM limit.

        Args:
            token_id: UUID of the token to rotate.
            db_session: Async database session.

        Returns:
            RotateTokenResponse with new token details.
        """
        # Look up old token
        stmt = select(A2ATokenRecord).where(
            A2ATokenRecord.id == token_id
        )
        result = await db_session.execute(stmt)
        old_record = result.scalar_one_or_none()

        if old_record is None:
            return {"error": "Token not found"}

        # Revoke old
        old_record.is_revoked = True
        old_record.revoked_at = datetime.now(UTC)
        invalidate_cache()

        # Create new with same config
        raw_token = f"nexus-a2a-{secrets.token_urlsafe(32)}"
        new_record = A2ATokenRecord(
            token_hash=_hash_token(raw_token),
            name=old_record.name,
            allowed_skills=old_record.allowed_skills,
            rate_limit_rpm=old_record.rate_limit_rpm,
            expires_at=old_record.expires_at,
        )
        db_session.add(new_record)
        await db_session.commit()
        await db_session.refresh(new_record)

        logger.info(
            "a2a_token_rotated",
            old_id=token_id,
            new_id=str(new_record.id),
            name=new_record.name,
        )

        return RotateTokenResponse(
            old_token_id=token_id,
            old_revoked=True,
            new_token=CreateTokenResponse(
                id=str(new_record.id),
                name=new_record.name,
                raw_token=raw_token,
                allowed_skills=new_record.allowed_skills,
                rate_limit_rpm=new_record.rate_limit_rpm,
                expires_at=(
                    str(new_record.expires_at)
                    if new_record.expires_at
                    else None
                ),
            ),
        )
