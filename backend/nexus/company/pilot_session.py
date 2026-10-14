"""Disposable supervised UAT sessions use real password verification and existing JWT issuer."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from litestar.exceptions import NotAuthorizedException
from pydantic import BaseModel, ConfigDict, Field

from nexus.api.auth import create_access_token, hash_password, verify_password
from nexus.api.company_auth import validate_company_auth_configuration
from nexus.company.access import (
    Capability,
    CompanyDirectory,
    VerifiedIdentity,
    resolve_principal_access,
)
from nexus.company.pilot_session_store import (
    PilotCredential,
    PilotCredentialFile,
    load_credentials,
    save_credentials,
)


class PilotLogin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)


class PilotSignup(PilotLogin):
    invitation: str = Field(min_length=32, max_length=256)


class PilotUser(BaseModel):
    user_id: UUID
    workspace_id: UUID
    company_id: UUID
    email: str
    display_name: str


class PilotSessionToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: PilotUser


class PilotSessionService:
    def __init__(self, directory: CompanyDirectory, account_file: Path) -> None:
        self.directory, self.account_file = directory, account_file
        self._lock = asyncio.Lock()
        validate_company_auth_configuration()
        load_credentials(account_file)

    async def login(self, data: PilotLogin) -> PilotSessionToken:
        async with self._lock:
            account = self._account(load_credentials(self.account_file), data.email)
            valid = bool(
                account
                and account.password_hash
                and await asyncio.to_thread(verify_password, data.password, account.password_hash)
            )
            if not valid or account is None:
                raise NotAuthorizedException(detail="Task session credentials are unavailable")
            await self._current(account)
            return self._token(account)

    async def signup(self, data: PilotSignup) -> PilotSessionToken:
        async with self._lock:
            stored = load_credentials(self.account_file)
            account = self._account(stored, data.email)
            digest = hashlib.sha256(data.invitation.encode()).hexdigest()
            if (
                account is None
                or account.password_hash is not None
                or account.signup_sha256 is None
                or account.signup_expires_at is None
                or account.signup_expires_at <= datetime.now(UTC)
                or not hmac.compare_digest(digest, account.signup_sha256)
            ):
                raise NotAuthorizedException(detail="Task session invitation is unavailable")
            password = await asyncio.to_thread(hash_password, data.password)
            await self._current(account)
            if (
                account.signup_expires_at <= datetime.now(UTC)
                or load_credentials(self.account_file) != stored
            ):
                raise NotAuthorizedException(detail="Task session invitation changed or expired")
            current = account.model_copy(
                update={"password_hash": password, "signup_sha256": None, "signup_expires_at": None}
            )
            save_credentials(
                self.account_file,
                stored.model_copy(
                    update={
                        "accounts": tuple(
                            current if row.principal_id == account.principal_id else row
                            for row in stored.accounts
                        )
                    }
                ),
            )
            return self._token(current)

    async def _current(self, account: PilotCredential) -> None:
        try:
            await resolve_principal_access(
                VerifiedIdentity(
                    principal_id=account.principal_id, workspace_id=account.workspace_id
                ),
                self.directory,
                company_id=account.company_id,
                capability=Capability.READ,
                task_id=uuid4(),
                trace_id=uuid4(),
            )
        except ValueError as exc:
            raise NotAuthorizedException(
                detail="Current task session account is unavailable"
            ) from exc

    @staticmethod
    def _account(stored: PilotCredentialFile, email: str) -> PilotCredential | None:
        return next(
            (
                row
                for row in stored.accounts
                if hmac.compare_digest(row.email.casefold().encode(), email.casefold().encode())
            ),
            None,
        )

    @staticmethod
    def _token(account: PilotCredential) -> PilotSessionToken:
        return PilotSessionToken(
            access_token=create_access_token(
                user_id=str(account.principal_id),
                workspace_id=str(account.workspace_id),
                email=account.email,
            ),
            user=PilotUser(
                user_id=account.principal_id,
                workspace_id=account.workspace_id,
                company_id=account.company_id,
                email=account.email,
                display_name=account.display_name,
            ),
        )
