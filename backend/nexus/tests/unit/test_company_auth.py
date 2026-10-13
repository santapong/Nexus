"""Strict company JWT authentication has no anonymous personal-mode fallback."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt
import pytest
from litestar.exceptions import (
    NotAuthorizedException,
    PermissionDeniedException,
    ServiceUnavailableException,
)

from nexus.api.company_auth import (
    require_company_identity,
    resolve_company_control,
    resolve_company_scope,
)
from nexus.company.access import Capability, CompanyDirectory, PrincipalAccess, WorkAccess
from nexus.settings import settings
from nexus.tests.unit.test_company_access import WORKSPACE, access, directory
from nexus.tests.unit.test_company_foundation import ACTOR, COMPANY, OWNER, TASK, TRACE

TEST_KEY = "company-auth-test-key-at-least-32-bytes-long"


@pytest.fixture(autouse=True)
def jwt_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use a public synthetic key; no real provider or credential is read."""
    monkeypatch.setattr(settings, "jwt_secret_key", TEST_KEY)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")


def token(changes: dict[str, object] | None = None, *, remove: str | None = None) -> str:
    """Sign realistic claims so malformed payload tests exercise actual JWT verification."""
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": str(ACTOR),
        "workspace_id": str(WORKSPACE),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }
    claims.update(changes or {})
    if remove:
        del claims[remove]
    return jwt.encode(claims, TEST_KEY, algorithm="HS256")


def request(header: str | None = None) -> MagicMock:
    """Supply the actual header interface without invoking a running API."""
    result = MagicMock()
    result.headers = {"authorization": header} if header is not None else {}
    return result


def test_verified_uuid_identity_ignores_self_issued_owner_claims() -> None:
    identity = require_company_identity(
        request(f"Bearer {token({'role': 'owner', 'company_id': str(COMPANY)})}")
    )
    assert identity.principal_id == ACTOR and identity.workspace_id == WORKSPACE
    assert not hasattr(identity, "role")


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer", "Bearer ", "Bearer bad.jwt"])
def test_missing_or_malformed_tokens_never_use_personal_mode(
    header: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "personal_mode", True)
    with pytest.raises(NotAuthorizedException):
        require_company_identity(request(header))


@pytest.mark.parametrize("claim", ["sub", "workspace_id", "exp", "iat"])
def test_required_claims_cannot_be_omitted(claim: str) -> None:
    with pytest.raises(NotAuthorizedException):
        require_company_identity(request(f"Bearer {token(remove=claim)}"))


@pytest.mark.parametrize(
    "changes",
    [
        {"sub": ""},
        {"workspace_id": ""},
        {"sub": "non-uuid"},
        {"workspace_id": "non-uuid"},
        {"workspace_id": 1},
        {"exp": 0},
        {"exp": True},
        {"exp": "9999999999"},
        {"iat": "1"},
        {"iat": 9_999_999_999},
    ],
)
def test_invalid_identity_or_time_claims_are_authentication_failures(
    changes: dict[str, object],
) -> None:
    with pytest.raises(NotAuthorizedException):
        require_company_identity(request(f"Bearer {token(changes)}"))


def test_signature_and_algorithm_are_verified() -> None:
    foreign = jwt.encode(
        {"sub": str(ACTOR), "workspace_id": str(WORKSPACE), "iat": 1, "exp": 9_999_999_999},
        "different-public-test-signing-key-of-32-bytes",
        algorithm="HS256",
    )
    with pytest.raises(NotAuthorizedException):
        require_company_identity(request(f"Bearer {foreign}"))
    unsigned = jwt.encode({"sub": str(ACTOR)}, "", algorithm="none")
    with pytest.raises(NotAuthorizedException):
        require_company_identity(request(f"Bearer {unsigned}"))


@pytest.mark.parametrize("field,value", [("jwt_secret_key", ""), ("jwt_algorithm", "none")])
def test_missing_or_unsigned_authentication_configuration_fails_closed(
    field: str, value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = token()
    monkeypatch.setattr(settings, field, value)
    with pytest.raises(ServiceUnavailableException):
        require_company_identity(request(f"Bearer {signed}"))


@pytest.mark.parametrize("key", ["secret", "nexus-dev-secret-change-in-production", "short"])
def test_weak_company_signing_key_is_unavailable_even_in_development(
    key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = token()
    monkeypatch.setattr(settings, "jwt_secret_key", key)
    with pytest.raises(ServiceUnavailableException):
        require_company_identity(request(f"Bearer {signed}"))


async def test_resolver_uses_live_mapping_and_registered_work() -> None:
    source = directory()
    scope = await resolve_company_scope(
        request(f"Bearer {token()}"),
        source,
        company_id=COMPANY,
        task_id=TASK,
        trace_id=TRACE,
        capability=Capability.INTERNAL_PROPOSAL,
    )
    assert scope.principal_id == ACTOR and scope.task_id == TASK
    assert source.lookup_principal.await_count == source.lookup_work.await_count == 1


async def test_valid_token_with_removed_membership_is_forbidden() -> None:
    source = directory()
    source.lookup_principal.return_value = None
    with pytest.raises(PermissionDeniedException):
        await resolve_company_scope(
            request(f"Bearer {token()}"),
            source,
            company_id=COMPANY,
            task_id=TASK,
            trace_id=TRACE,
            capability=Capability.READ,
        )


async def test_token_owner_claim_cannot_approve_without_actual_owner_directory() -> None:
    with pytest.raises(PermissionDeniedException):
        await resolve_company_scope(
            request(f"Bearer {token({'role': 'owner'})}"),
            directory(),
            company_id=COMPANY,
            task_id=TASK,
            trace_id=TRACE,
            capability=Capability.APPROVE,
        )


async def test_bad_token_is_rejected_before_directory_lookup() -> None:
    source = AsyncMock(spec=CompanyDirectory)
    with pytest.raises(NotAuthorizedException):
        await resolve_company_scope(
            request(),
            source,
            company_id=COMPANY,
            task_id=TASK,
            trace_id=TRACE,
            capability=Capability.READ,
        )
    source.lookup_principal.assert_not_awaited()
    source.lookup_work.assert_not_awaited()


async def test_directory_foreign_work_cannot_be_scoped_by_authenticated_payload() -> None:
    source = directory(access())
    source.lookup_work.return_value = WorkAccess.model_validate(
        source.lookup_work.return_value.model_dump() | {"company_id": UUID(int=99)}
    )
    with pytest.raises(PermissionDeniedException):
        await resolve_company_scope(
            request(f"Bearer {token()}"),
            source,
            company_id=COMPANY,
            task_id=TASK,
            trace_id=TRACE,
            capability=Capability.READ,
        )


async def test_inactive_current_principal_denies_even_with_valid_jwt() -> None:
    inactive = PrincipalAccess.model_validate(access().model_dump() | {"principal_active": False})
    with pytest.raises(PermissionDeniedException):
        await resolve_company_scope(
            request(f"Bearer {token()}"),
            directory(inactive),
            company_id=COMPANY,
            task_id=TASK,
            trace_id=TRACE,
            capability=Capability.READ,
        )


@pytest.mark.parametrize("capability", [Capability.PAUSE, Capability.GRANT, Capability.INITIALIZE])
async def test_owner_control_works_before_work_exists_and_uses_new_server_audit_identity(
    capability: Capability,
) -> None:
    source = directory(access(OWNER))
    source.lookup_work.return_value = None
    owner_request = request(f"Bearer {token({'sub': str(OWNER)})}")
    first = await resolve_company_control(
        owner_request, source, company_id=COMPANY, capability=capability
    )
    second = await resolve_company_control(
        owner_request, source, company_id=COMPANY, capability=capability
    )
    assert first.principal_id == OWNER
    assert first.operation_id != second.operation_id and first.trace_id != second.trace_id
    assert not hasattr(first, "task_id")
    source.lookup_work.assert_not_awaited()


async def test_company_control_rejects_non_owner_and_work_capabilities() -> None:
    with pytest.raises(PermissionDeniedException):
        await resolve_company_control(
            request(f"Bearer {token()}"),
            directory(),
            company_id=COMPANY,
            capability=Capability.PAUSE,
        )
    with pytest.raises(PermissionDeniedException):
        await resolve_company_control(
            request(f"Bearer {token({'sub': str(OWNER)})}"),
            directory(access(OWNER)),
            company_id=COMPANY,
            capability=Capability.INTERNAL_PROPOSAL,
        )


async def test_company_control_rechecks_revoked_owner_membership() -> None:
    source = directory(access(OWNER))
    source.lookup_principal.return_value = PrincipalAccess.model_validate(
        access(OWNER).model_dump() | {"membership_active": False}
    )
    with pytest.raises(PermissionDeniedException):
        await resolve_company_control(
            request(f"Bearer {token({'sub': str(OWNER)})}"),
            source,
            company_id=COMPANY,
            capability=Capability.PAUSE,
        )
    source.lookup_work.assert_not_awaited()
