"""UAT credential isolation and offline catalog admissions; no real account or provider call."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.pilot_catalog import offline_registration, pilot_catalog
from nexus.company.pilot_composition import compose_pilot
from nexus.company.pilot_config import PilotConfig
from nexus.company.pilot_session_store import (
    PilotCredentialFile,
    load_credentials,
    save_credentials,
)
from nexus.company.pilot_setup import initialize_task
from nexus.settings import settings


def sdk_receipt(root: Path, *, requests: int = 1) -> Path:
    path = root / "sdk.json"
    path.write_text(
        json.dumps(
            {
                "model": "TestModel",
                "requests": requests,
                "criteria_passed": 2,
                "criteria_total": 2,
                "score": "1",
                "observed_at": datetime.now(UTC).isoformat(),
            }
        )
    )
    return path


def test_private_initialization_preserves_invitation_and_unique_account_binding(
    tmp_path: Path,
) -> None:
    config = initialize_task(tmp_path / "task", sdk_receipt(tmp_path))
    accounts = load_credentials(config.account_file)
    owner, member = accounts.accounts
    assert owner.principal_id == config.owner_id and owner.company_id == config.company_id
    assert owner.password_hash is None and owner.signup_sha256 is not None
    assert member.principal_id == config.member_id and member.password_hash is not None
    assert owner.workspace_id == member.workspace_id == config.workspace_id
    for name in ("config.json", "signer.json", "browser-credentials.json", "accounts.json"):
        assert (config.account_file.parent / name).stat().st_mode & 0o077 == 0
    before = {path.name: path.read_bytes() for path in config.account_file.parent.iterdir()}
    with pytest.raises(FileExistsError):
        initialize_task(config.account_file.parent, config.sdk_receipt)
    assert {path.name: path.read_bytes() for path in config.account_file.parent.iterdir()} == before


def test_credentials_deny_permissions_symlinks_and_duplicate_accounts(tmp_path: Path) -> None:
    config = initialize_task(tmp_path / "task", sdk_receipt(tmp_path))
    account_file = config.account_file
    stored = load_credentials(account_file)
    account_file.chmod(0o644)
    with pytest.raises(ValueError, match="private permissions"):
        load_credentials(account_file)
    account_file.chmod(0o600)
    link = account_file.parent / "alias.json"
    link.symlink_to(account_file)
    with pytest.raises(ValueError, match="unavailable"):
        load_credentials(link)
    with pytest.raises(ValueError, match="unique"):
        PilotCredentialFile(accounts=(stored.accounts[0], stored.accounts[0]))
    save_credentials(account_file, stored)
    assert load_credentials(account_file) == stored


def test_offline_catalog_has_finite_qualification_and_no_model_request_permission(
    tmp_path: Path,
) -> None:
    config = initialize_task(tmp_path / "task", sdk_receipt(tmp_path))
    model = offline_registration(config)
    assert model.provider == "test" and model.model_id == "test"
    assert model.health.expires_at - model.health.checked_at == timedelta(hours=4)
    assert all(item.expires_at > item.evaluated_at for item in model.evaluations)
    catalog = pilot_catalog(config)
    assert {row.tool for row in catalog.tools} == {
        "company.report.write.v1",
        "company.report.check.v1",
    }
    assert "model.request.v1" not in {row.tool for row in catalog.tools}
    config.sdk_receipt.write_text(
        json.dumps(
            {
                "model": "TestModel",
                "requests": 2,
                "criteria_passed": 2,
                "criteria_total": 2,
            }
        )
    )
    with pytest.raises(ValueError, match="unavailable"):
        offline_registration(config)


def test_uat_config_rejects_admin_other_database_and_short_initial_password(tmp_path: Path) -> None:
    receipt = sdk_receipt(tmp_path)
    root = tmp_path / "invalid-password"
    with pytest.raises(ValueError, match="12 to 256"):
        initialize_task(root, receipt, "short")
    assert not tuple(root.iterdir())
    config = initialize_task(tmp_path / "task", receipt)
    for url in (
        config.database_url.replace("nexus_company_app@", "santapong@"),
        config.database_url.replace("nexus_company_test_owner_uat", "another_database"),
    ):
        with pytest.raises(ValueError, match="exclusive restricted-role"):
            PilotConfig.model_validate(config.model_dump() | {"database_url": url})


def test_pilot_mounts_saved_reports_without_implicit_preparation_or_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner read/snapshot controls use the configured store; effects stay unconfigured."""
    config = initialize_task(tmp_path / "task", sdk_receipt(tmp_path))
    monkeypatch.setattr(
        settings, "jwt_secret_key", "unit-only-company-key-at-least-thirty-two-characters"
    )
    services = compose_pilot(async_sessionmaker[AsyncSession](), config)
    assert services.management.reports is services.reports
    assert services.management.report_preparation is None
