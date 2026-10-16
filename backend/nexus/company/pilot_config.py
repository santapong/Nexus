"""Explicit disposable owner UAT composition configuration, not production credentials."""

import re
from pathlib import Path
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator
from sqlalchemy.engine import make_url

from nexus.company.access import CompanyControlScope, VerifiedIdentity

PilotProfile = Literal["disposable-supervised-owner-uat-v1", "local-nexus-owner-preview-v1"]
PREVIEW_PROFILE = "local-nexus-owner-preview-v1"


def preview_database_name(value: str) -> str:
    if (
        len(value) > 63
        or re.fullmatch(r"nexus_company_test_owner_preview_[a-z0-9_]{1,30}", value) is None
    ):
        raise ValueError("Preview requires its exclusive restricted-role database")
    return value


class PilotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: PilotProfile = "disposable-supervised-owner-uat-v1"
    company_id: UUID
    workspace_id: UUID
    owner_id: UUID
    author_id: UUID
    verifier_id: UUID
    member_id: UUID
    department_id: UUID
    goal_id: UUID
    public_source_id: UUID
    public_resource_id: UUID
    private_source_id: UUID
    private_resource_id: UUID
    report_resource_id: UUID
    check_resource_id: UUID
    created_at: AwareDatetime
    database_url: str
    blob_root: Path
    account_file: Path
    sdk_receipt: Path | None
    docs_manifest: Path | None = None
    docs_manifest_sha256: str | None = None

    @model_validator(mode="after")
    def isolated_database(self) -> Self:
        url = make_url(self.database_url)
        if (
            url.drivername != "postgresql+asyncpg"
            or url.username != "nexus_company_app"
            or url.password is not None
            or not url.database
            or url.query.get("host") != "/tmp/nexus-release-tests-2026-10-13/socket"
            or url.query.get("port") != "55438"
            or url.host is not None
        ):
            raise ValueError("Disposable UAT requires its exclusive restricted-role database")
        if self.profile == PREVIEW_PROFILE:
            preview_database_name(url.database)
            if (
                dict(url.query)
                != {"host": "/tmp/nexus-release-tests-2026-10-13/socket", "port": "55438"}
                or self.sdk_receipt is not None
                or self.docs_manifest is None
                or re.fullmatch(r"[0-9a-f]{64}", self.docs_manifest_sha256 or "") is None
            ):
                raise ValueError("Preview requires exact document pins and no model qualification")
        elif url.database != "nexus_company_test_owner_uat" or self.sdk_receipt is None:
            raise ValueError("Disposable UAT requires its exclusive restricted-role database")
        return self

    @property
    def admin_database_url(self) -> str:
        return str(make_url(self.database_url).set(username="santapong"))

    def control(self) -> CompanyControlScope:

        return CompanyControlScope(
            company_id=self.company_id,
            principal_id=self.owner_id,
            operation_id=uuid4(),
            trace_id=uuid4(),
        )

    def identity(self) -> VerifiedIdentity:

        return VerifiedIdentity(principal_id=self.owner_id, workspace_id=self.workspace_id)
