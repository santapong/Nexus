"""Actual synthetic signature verification retains a process-only credential deadline."""

# TASK: Verify a supplied credential and retain its exact expiry without minting authority.
# FILES: NEW worker_identity.py and this unit file only.
# DONE: Real synthetic JWT checks and final expiry deny; no owner/member/effect shortcut.
# RISK: Authentication boundary; Root separately integrates current directory/effect gates.

import asyncio
import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import jwt
import pytest
from pydantic import SecretStr

from nexus.company.access import VerifiedIdentity
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    NotificationWorkerIdentities,
    WorkerIdentityDeniedError,
)
from nexus.tests.unit.test_company_management_contracts import binding

TEST_KEY = "notification-worker-public-synthetic-key-at-least-64-characters-long-for-tests"
FOREIGN_KEY = "notification-worker-other-synthetic-key-at-least-64-characters-long-for-tests"


class FixtureCredential:
    """A supplied synthetic credential is separate from any issuer or persisted secret."""

    def __init__(self, credential: SecretStr) -> None:
        self.value = credential
        self.requests = 0

    async def credential(self) -> SecretStr:
        """Supply the one configured test token; it confers no directory or owner role."""
        self.requests += 1
        return self.value


def signed(
    changes: dict[str, object] | None = None,
    *,
    omitted: str | None = None,
    algorithm: str = "HS256",
    key: str = TEST_KEY,
) -> str:
    """Only test fixtures issue tokens; production worker code has no encode path."""
    expected = binding()
    now = int(datetime.now(UTC).timestamp())
    claims: dict[str, object] = {
        "sub": str(expected.actor_id),
        "workspace_id": str(expected.workspace_id),
        "iat": now - 1,
        "exp": now + 300,
    }
    claims.update(changes or {})
    if omitted is not None:
        del claims[omitted]
    return jwt.encode(claims, key, algorithm=algorithm)


def adapter(token: str) -> tuple[NotificationWorkerIdentities, FixtureCredential]:
    provider = FixtureCredential(SecretStr(token))
    return NotificationWorkerIdentities(provider, SecretStr(TEST_KEY), enabled=True), provider


async def test_verified_token_retains_only_identity_and_exact_credential_dates() -> None:
    now = int(datetime.now(UTC).timestamp())
    token = signed(
        {"iat": now - 10, "exp": now + 300, "role": "owner", "company_id": str(UUID(int=999))}
    )
    identities, provider = adapter(token)
    witness = await identities.current(binding())
    assert witness.identity == VerifiedIdentity(
        principal_id=binding().actor_id, workspace_id=binding().workspace_id
    )
    assert witness.issued_at == datetime.fromtimestamp(now - 10, UTC)
    assert witness.expires_at == datetime.fromtimestamp(now + 300, UTC)
    witness.require_time(datetime.now(UTC))
    assert provider.requests == 1
    assert token not in repr(witness) and TEST_KEY not in repr(witness)
    assert not hasattr(witness, "role") and not hasattr(witness, "company_id")


async def test_disabled_worker_does_not_fetch_or_create_credentials() -> None:
    provider = FixtureCredential(SecretStr(signed()))
    disabled = NotificationWorkerIdentities(provider, SecretStr(TEST_KEY))
    with pytest.raises(WorkerIdentityDeniedError):
        await disabled.current(binding())
    with pytest.raises(WorkerIdentityDeniedError):
        await NotificationWorkerIdentities().current()
    assert provider.requests == 0


async def test_signed_identity_can_support_owner_read_tick_before_binding_exists() -> None:
    identities, provider = adapter(signed())
    witness = await identities.current()
    assert witness.identity.principal_id == binding().actor_id and provider.requests == 1


@pytest.mark.parametrize("claim", ["sub", "workspace_id", "iat", "exp"])
async def test_required_claims_are_verified_before_producing_identity(claim: str) -> None:
    identities, _ = adapter(signed(omitted=claim))
    with pytest.raises(WorkerIdentityDeniedError):
        await identities.current()


@pytest.mark.parametrize(
    "changes",
    [
        {"iat": False},
        {"iat": True},
        {"iat": "1"},
        {"iat": 1.0},
        {"exp": False},
        {"exp": True},
        {"exp": "9999999999"},
        {"exp": 9999999999.0},
        {"sub": "not-a-uuid"},
        {"workspace_id": "not-a-uuid"},
        {"sub": 1},
        {"workspace_id": 1},
        {"iat": 9999999999},
        {"exp": 0},
        {"exp": 10**20},
        {"iat": -(10**20)},
    ],
)
async def test_malformed_expired_or_future_claims_cannot_be_worker_identity(
    changes: dict[str, object],
) -> None:
    identities, _ = adapter(signed(changes))
    with pytest.raises(WorkerIdentityDeniedError):
        await identities.current()


@pytest.mark.parametrize("problem", ["foreign_key", "tamper", "algorithm", "unsigned", "malformed"])
async def test_signature_and_closed_algorithm_are_actual_authentication_requirements(
    problem: str,
) -> None:
    token = signed()
    if problem == "foreign_key":
        token = signed(key=FOREIGN_KEY)
    elif problem == "tamper":
        head, body, signature = token.split(".")
        changed = ("A" if signature[0] != "A" else "B") + signature[1:]
        token = ".".join((head, body, changed))
    elif problem == "algorithm":
        token = signed(algorithm="HS512")
    elif problem == "unsigned":
        token = signed(algorithm="none", key="")
    else:
        token = "synthetic-private-malformed-token"
    identities, _ = adapter(token)
    with pytest.raises(WorkerIdentityDeniedError) as error:
        await identities.current()
    assert token not in str(error.value) and TEST_KEY not in str(error.value)


@pytest.mark.parametrize("field", ["actor_id", "workspace_id"])
async def test_credential_must_match_actual_expected_work_actor_and_workspace(field: str) -> None:
    identities, _ = adapter(signed())
    mismatch = binding().model_copy(update={field: UUID(int=990)})
    with pytest.raises(WorkerIdentityDeniedError):
        await identities.current(mismatch)


@pytest.mark.parametrize("key", [None, "", "short", "nexus-dev-secret-change-in-production"])
def test_enabled_worker_requires_explicit_strong_signer_configuration(key: str | None) -> None:
    provider = FixtureCredential(SecretStr(signed()))
    with pytest.raises(WorkerIdentityDeniedError):
        NotificationWorkerIdentities(
            provider, SecretStr(key) if key is not None else None, enabled=True
        )


async def test_final_time_gate_denies_expiry_and_does_not_refresh_supplied_token() -> None:
    identities, provider = adapter(signed())
    witness = await identities.current()
    with pytest.raises(WorkerIdentityDeniedError):
        witness.require_time(witness.expires_at)
    with pytest.raises(WorkerIdentityDeniedError):
        witness.require_time(witness.issued_at - timedelta(microseconds=1))
    with pytest.raises(WorkerIdentityDeniedError):
        witness.require_time(datetime.now())
    assert provider.requests == 1


async def test_credential_expiring_during_actual_await_denies_final_execution_time() -> None:
    now = int(datetime.now(UTC).timestamp())
    identities, provider = adapter(signed({"iat": now - 1, "exp": now + 2}))
    witness = await identities.current()
    await asyncio.sleep(max(0, (witness.expires_at - datetime.now(UTC)).total_seconds()) + 0.03)
    with pytest.raises(WorkerIdentityDeniedError):
        witness.require_time(datetime.now(UTC))
    assert provider.requests == 1


def test_public_dataclass_constructor_cannot_create_a_verified_witness_from_owner_id() -> None:
    with pytest.raises(WorkerIdentityDeniedError):
        AuthenticatedWorkerIdentity(
            identity=VerifiedIdentity(
                principal_id=binding().actor_id, workspace_id=binding().workspace_id
            ),
            issued_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )


async def test_process_witness_is_frozen_and_has_no_json_wire_encoder() -> None:
    identities, _ = adapter(signed())
    witness = await identities.current()
    with pytest.raises(FrozenInstanceError):
        field_name: str = "expires_at"
        setattr(witness, field_name, witness.expires_at + timedelta(days=1))
    with pytest.raises(TypeError):
        json.dumps(witness)
    assert not hasattr(witness, "model_dump_json")


async def test_opaque_provider_error_cannot_reflect_credential_or_signing_key() -> None:
    token = signed()

    class UnavailableCredential:
        async def credential(self) -> SecretStr:
            raise RuntimeError(token + TEST_KEY)

    identities = NotificationWorkerIdentities(
        UnavailableCredential(), SecretStr(TEST_KEY), enabled=True
    )
    with pytest.raises(WorkerIdentityDeniedError) as error:
        await identities.current()
    assert token not in str(error.value) and TEST_KEY not in str(error.value)
    assert error.value.__suppress_context__


async def test_cancellation_of_credential_acquisition_propagates_without_identity() -> None:
    class CancelledCredential:
        async def credential(self) -> SecretStr:
            raise asyncio.CancelledError

    identities = NotificationWorkerIdentities(
        CancelledCredential(), SecretStr(TEST_KEY), enabled=True
    )
    with pytest.raises(asyncio.CancelledError):
        await identities.current()


@pytest.mark.parametrize("token", ["", " padded ", "x" * 16_385])
async def test_missing_padded_or_oversized_credential_is_not_normalized(token: str) -> None:
    identities, _ = adapter(token)
    with pytest.raises(WorkerIdentityDeniedError):
        await identities.current()


@pytest.mark.parametrize("enabled", [0, 1, "true"])
def test_worker_enablement_requires_literal_operator_boolean(enabled: object) -> None:
    # The negative fixture deliberately violates the annotation; cast does not coerce the value.
    with pytest.raises(WorkerIdentityDeniedError):
        NotificationWorkerIdentities(enabled=cast(bool, enabled))
