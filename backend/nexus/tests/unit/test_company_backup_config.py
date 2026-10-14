"""Declared operator configuration cannot become URL, selector, activation or reset authority."""

from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.operations.backup_config import LocalPostgresBackupConfig
from nexus.operations.backup_postgres import require_custom_dump


def configuration(**updates: object) -> LocalPostgresBackupConfig:
    values: dict[str, object] = {
        "company_id": UUID(int=1),
        "socket": Path("/tmp/private-socket"),
        "port": 55438,
        "admin_user": "santapong",
        "source_database": "nexus_company_test_backup_source",
        "target_database": "nexus_company_test_backup_restore",
        "restore_root": Path("/tmp/new-root"),
        **updates,
    }
    return LocalPostgresBackupConfig.model_validate(values)


def test_operator_defaults_disabled() -> None:
    with pytest.raises(ValueError, match="disabled"):
        configuration().require_enabled()


@pytest.mark.parametrize(
    "updates",
    [
        {"target_database": "nexus_company_test_backup_source"},
        {"source_database": "postgres://secret"},
        {"admin_user": "admin --clean"},
        {"port": True},
        {"enabled": "true"},
        {"socket": Path("relative")},
        {"max_bytes": 268435457},
        {"timeout_seconds": 181},
    ],
)
def test_invalid_server_configuration_is_not_normalized(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        configuration(**updates)


@pytest.mark.parametrize("raw", [b"", b"not PG dump", b"PGDMP" + b"x" * 10])
def test_custom_dump_size_and_magic_are_bounded(raw: bytes) -> None:
    with pytest.raises(ValueError):
        require_custom_dump(raw, 10)
