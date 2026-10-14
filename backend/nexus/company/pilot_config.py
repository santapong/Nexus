"""Explicit disposable owner UAT composition configuration, not production credentials."""

from pathlib import Path
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator
from sqlalchemy.engine import make_url

from nexus.company.access import CompanyControlScope, VerifiedIdentity


class PilotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: Literal["disposable-supervised-owner-uat-v1"] = "disposable-supervised-owner-uat-v1"
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
    sdk_receipt: Path

    @model_validator(mode="after")
    def isolated_database(self) -> Self:
        url = make_url(self.database_url)
        if (
            url.drivername != "postgresql+asyncpg"
            or url.username != "nexus_company_app"
            or url.password is not None
            or url.database != "nexus_company_test_owner_uat"
            or url.query.get("host") != "/tmp/nexus-release-tests-2026-10-13/socket"
            or url.query.get("port") != "55438"
            or url.host is not None
        ):
            raise ValueError("Disposable UAT requires its exclusive restricted-role database")
        return self

    def control(self) -> CompanyControlScope:

        return CompanyControlScope(
            company_id=self.company_id,
            principal_id=self.owner_id,
            operation_id=uuid4(),
            trace_id=uuid4(),
        )

    def identity(self) -> VerifiedIdentity:

        return VerifiedIdentity(principal_id=self.owner_id, workspace_id=self.workspace_id)
