"""Private synthetic recipient configuration, not owner setup or email permission."""

from pathlib import Path
from uuid import UUID

import pytest

from nexus.company.notifications.recipient_registry import (
    FileOwnerRecipients,
    RecipientConfigurationError,
    RecipientRegistryFile,
)
from nexus.tests.notification_rule_fixtures import COMPANY, NOW, OWNER, recipient


def configured_file(root: Path) -> Path:
    path = root / "synthetic-owner-recipients.json"
    path.write_text(RecipientRegistryFile(policies=(recipient(),)).model_dump_json())
    path.chmod(0o600)
    return path


@pytest.mark.asyncio
async def test_actual_file_current_policy_is_separate_from_owner_role(tmp_path: Path) -> None:
    registry = FileOwnerRecipients(configured_file(tmp_path))
    assert await registry.current(COMPANY, OWNER, NOW) == recipient()
    assert await registry.current(COMPANY, UUID(int=900), NOW) is None
    assert await registry.current(UUID(int=900), OWNER, NOW) is None
    assert await registry.current(COMPANY, OWNER, recipient().expires_at) is None


@pytest.mark.asyncio
async def test_policy_change_during_preparation_rejects_original_pin(tmp_path: Path) -> None:
    path = configured_file(tmp_path)
    registry = FileOwnerRecipients(path)
    old = await registry.current(COMPANY, OWNER, NOW)
    assert old is not None
    changed = recipient().model_copy(
        update={"recipient": "changed@example.invalid", "version": "owner-email.2"}
    )
    path.write_text(RecipientRegistryFile(policies=(changed,)).model_dump_json())
    assert await registry.current(COMPANY, OWNER, NOW) == changed
    with pytest.raises(RecipientConfigurationError):
        registry.require_current(old, NOW)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [0o644, 0o666])
async def test_nonprivate_config_blocks_without_address_reflection(
    tmp_path: Path, mode: int
) -> None:
    path = configured_file(tmp_path)
    path.chmod(mode)
    with pytest.raises(
        RecipientConfigurationError, match=r"^Owner recipient configuration is unavailable$"
    ):
        await FileOwnerRecipients(path).current(COMPANY, OWNER, NOW)


@pytest.mark.asyncio
async def test_symlink_missing_and_oversize_config_deny(tmp_path: Path) -> None:
    path = configured_file(tmp_path)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    for candidate in (link, tmp_path / "missing.json"):
        with pytest.raises(RecipientConfigurationError):
            await FileOwnerRecipients(candidate).current(COMPANY, OWNER, NOW)
    path.write_bytes(b"x" * 65_537)
    with pytest.raises(RecipientConfigurationError):
        await FileOwnerRecipients(path).current(COMPANY, OWNER, NOW)


@pytest.mark.asyncio
async def test_malformed_secret_field_and_duplicate_owner_never_become_policy(
    tmp_path: Path,
) -> None:
    path = configured_file(tmp_path)
    original = RecipientRegistryFile(policies=(recipient(),)).model_dump_json()
    path.write_text(original[:-1] + ',"api_key":"fixture-secret"}')
    with pytest.raises(RecipientConfigurationError) as problem:
        await FileOwnerRecipients(path).current(COMPANY, OWNER, NOW)
    assert "fixture-secret" not in str(problem.value)
    path.write_text(
        '{"policies":[' + recipient().model_dump_json() + "," + recipient().model_dump_json() + "]}"
    )
    with pytest.raises(RecipientConfigurationError):
        await FileOwnerRecipients(path).current(COMPANY, OWNER, NOW)
