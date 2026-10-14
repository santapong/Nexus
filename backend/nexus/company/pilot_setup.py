"""Explicit CLI preparation writes only private disposable task credentials/configuration."""

import hashlib
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from nexus.api.auth import hash_password
from nexus.company.pilot_config import PilotConfig
from nexus.company.pilot_session_store import PilotCredential, PilotCredentialFile, save_credentials

UAT_DATABASE = "postgresql+asyncpg://nexus_company_app@/nexus_company_test_owner_uat?host=/tmp/nexus-release-tests-2026-10-13/socket&port=55438"


def private_json(path: Path, payload: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(payload, stream, sort_keys=True, indent=2)


def new_config(root: Path, sdk_receipt: Path) -> PilotConfig:
    return PilotConfig(
        **{
            field: uuid4()
            for field in (
                "company_id",
                "workspace_id",
                "owner_id",
                "author_id",
                "verifier_id",
                "member_id",
                "department_id",
                "goal_id",
                "public_source_id",
                "public_resource_id",
                "private_source_id",
                "private_resource_id",
                "report_resource_id",
                "check_resource_id",
            )
        },
        created_at=datetime.now(UTC),
        database_url=UAT_DATABASE,
        blob_root=root / "blobs",
        account_file=root / "accounts.json",
        sdk_receipt=sdk_receipt,
    )


def initialize_task(root: Path, sdk_receipt: Path, password: str | None = None) -> PilotConfig:
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    if root.is_symlink() or root.stat().st_mode & 0o077:
        raise ValueError("UAT task directory must be private")
    for name in ("config.json", "signer.json", "browser-credentials.json", "accounts.json"):
        if (root / name).exists() or (root / name).is_symlink():
            raise FileExistsError("An initialized UAT task cannot be overwritten")
    if password is not None and not 12 <= len(password) <= 256:
        raise ValueError("Disposable UAT password must contain 12 to 256 characters")
    config = new_config(root, sdk_receipt)
    owner_password = password or secrets.token_urlsafe(24)
    member_password = secrets.token_urlsafe(24)
    invitation = secrets.token_urlsafe(32)
    owner = PilotCredential(
        company_id=config.company_id,
        workspace_id=config.workspace_id,
        principal_id=config.owner_id,
        email="owner-uat@example.invalid",
        display_name="Disposable UAT owner",
        signup_sha256=hashlib.sha256(invitation.encode()).hexdigest(),
        signup_expires_at=config.created_at + timedelta(hours=8),
    )
    member = PilotCredential(
        company_id=config.company_id,
        workspace_id=config.workspace_id,
        principal_id=config.member_id,
        email="member-uat@example.invalid",
        display_name="Disposable UAT member",
        password_hash=hash_password(member_password),
    )
    save_credentials(config.account_file, PilotCredentialFile(accounts=(owner, member)))
    private_json(root / "config.json", config.model_dump(mode="json"))
    private_json(root / "signer.json", {"jwt_secret_key": secrets.token_urlsafe(48)})
    private_json(
        root / "browser-credentials.json",
        {
            "scope": "Disposable local UAT only; no production account",
            "owner": {"email": owner.email, "password": owner_password, "invitation": invitation},
            "member": {"email": member.email, "password": member_password},
        },
    )
    return config


def private_bytes(path: Path) -> bytes:
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Private task configuration is unavailable")
    if path.stat().st_mode & 0o077 or path.parent.stat().st_mode & 0o077:
        raise ValueError("Task configuration requires private permissions")
    if path.stat().st_size > 16384:
        raise ValueError("Task configuration exceeds its bound")
    return path.read_bytes()
