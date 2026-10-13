"""Strict JWT/live-directory company adapters; no personal-mode or legacy fallback."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol
from uuid import UUID, uuid4

import jwt
from litestar.exceptions import (
    NotAuthorizedException,
    PermissionDeniedException,
    ServiceUnavailableException,
)

from nexus.company.access import (
    AccessDeniedError,
    Capability,
    CompanyControlScope,
    CompanyDirectory,
    VerifiedIdentity,
    resolve_principal_access,
    resolve_work_scope,
)
from nexus.harness.journal_contracts import LedgerScope
from nexus.settings import settings


class AuthorizationRequest(Protocol):
    """Minimal typed request boundary; Litestar's headers implement Mapping."""

    @property
    def headers(self) -> Mapping[str, str]:
        """Expose header lookup without importing untyped application request state."""
        ...


def validate_company_auth_configuration() -> None:
    """Require a strong configured pilot signer in every environment, including development."""
    if (
        settings.jwt_algorithm != "HS256"
        or len(settings.jwt_secret_key) < 32
        or settings.jwt_secret_key == "nexus-dev-secret-change-in-production"
    ):
        raise ServiceUnavailableException(detail="Company authentication is not configured")


def require_company_identity(request: AuthorizationRequest) -> VerifiedIdentity:
    """Verify signature, required times and UUID claims; never trust token role/company."""
    header = request.headers.get("authorization", "")
    scheme, separator, token = header.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token or token.strip() != token:
        raise NotAuthorizedException(detail="Company authentication required")
    validate_company_auth_configuration()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub", "workspace_id"]},
        )
        if any(type(claims[name]) is not int for name in ("exp", "iat")) or any(
            not isinstance(claims[name], str) for name in ("sub", "workspace_id")
        ):
            raise ValueError("Malformed company identity claims")
        return VerifiedIdentity(
            principal_id=UUID(claims["sub"]), workspace_id=UUID(claims["workspace_id"])
        )
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError) as exc:
        raise NotAuthorizedException(detail="Company authentication required") from exc


async def resolve_company_scope(
    request: AuthorizationRequest,
    directory: CompanyDirectory,
    *,
    company_id: UUID,
    task_id: UUID,
    trace_id: UUID,
    capability: Capability,
) -> LedgerScope:
    """Resolve current principal and registered work; convert policy denials to HTTP 403."""
    identity = require_company_identity(request)
    try:
        access = await resolve_principal_access(
            identity,
            directory,
            company_id=company_id,
            capability=capability,
            task_id=task_id,
            trace_id=trace_id,
        )
        return await resolve_work_scope(
            access, directory, task_id=task_id, trace_id=trace_id, capability=capability
        )
    except AccessDeniedError as exc:
        raise PermissionDeniedException(detail="Company access denied") from exc


async def resolve_company_control(
    request: AuthorizationRequest,
    directory: CompanyDirectory,
    *,
    company_id: UUID,
    capability: Capability,
) -> CompanyControlScope:
    """Resolve owner init/pause/grant before work exists, using fresh server audit IDs."""
    identity = require_company_identity(request)
    if capability not in {Capability.PAUSE, Capability.GRANT, Capability.INITIALIZE}:
        raise PermissionDeniedException(detail="Unsupported company control")
    operation_id, trace_id = uuid4(), uuid4()
    try:
        access = await resolve_principal_access(
            identity,
            directory,
            company_id=company_id,
            capability=capability,
            task_id=operation_id,
            trace_id=trace_id,
        )
    except AccessDeniedError as exc:
        raise PermissionDeniedException(detail="Company control denied") from exc
    return CompanyControlScope(
        company_id=access.company_id,
        principal_id=access.principal_id,
        operation_id=operation_id,
        trace_id=trace_id,
    )
