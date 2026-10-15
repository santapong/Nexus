"""Transient signed fixture witness through the real verifier; no credential file or issuer API."""

import secrets
from datetime import timedelta

import jwt
from pydantic import SecretStr

from nexus.company.management.plans import RunBinding
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    NotificationWorkerIdentities,
)
from nexus.tests.unit.plan_admission_fixture_data import NOW, AdmissionFixture


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
