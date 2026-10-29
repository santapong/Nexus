"""Transient signed fixture witness through the real verifier; no credential file or issuer API."""

import secrets
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import SecretStr

from nexus.company.management.plans import RunBinding
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    NotificationWorkerIdentities,
)
from nexus.tests.unit.plan_admission_fixture_data import NOW, AdmissionFixture


@pytest.fixture(autouse=True)
def admission_case_clock(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """One actual per-case anchor for test data, SQL clock and genuine witness issuance."""
    from nexus.tests.unit import plan_admission_fixture_data as data
    from nexus.tests.unit import plan_admission_fixture_session as session
    from nexus.tests.unit import plan_admission_fixture_values as values

    anchor = datetime.now(UTC).replace(microsecond=0)
    for module in (data, session, values, request.module):
        monkeypatch.setattr(module, "NOW", anchor, raising=False)
    monkeypatch.setitem(globals(), "NOW", anchor)


class Provider:
    def __init__(self, value: SecretStr) -> None:
        self.value = value

    async def credential(self) -> SecretStr:
        return self.value


async def witness(data: AdmissionFixture) -> AuthenticatedWorkerIdentity:
    return await bound_witness(data.payload.procedure.binding)


async def bound_witness(bound: RunBinding) -> AuthenticatedWorkerIdentity:
    key = SecretStr(secrets.token_urlsafe(48))
    token = SecretStr(
        jwt.encode(
            {
                "sub": str(bound.actor_id),
                "workspace_id": str(bound.workspace_id),
                "iat": int((NOW - timedelta(seconds=1)).timestamp()),
                "exp": int((NOW + timedelta(seconds=600)).timestamp()),
            },
            key.get_secret_value(),
            algorithm="HS256",
        )
    )
    return await NotificationWorkerIdentities(Provider(token), key, enabled=True).current(bound)
