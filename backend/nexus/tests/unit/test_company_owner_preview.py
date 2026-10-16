"""Isolated local preview inputs; supplied documents, no DB/provider or real owner session."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from nexus.company.pilot_catalog import pilot_catalog
from nexus.company.pilot_config import PilotConfig
from nexus.company.pilot_setup import initialize_task


def documents(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repository"
    path = root / "docs/company-system/NEXUS_FOCUSED_DELIVERY_PLAN_2026-10-16.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Nexus\nOwner supervised local preview; execution remains disabled.\n")
    raw = path.read_bytes()
    manifest = tmp_path / "documents.json"
    manifest.write_text(
        json.dumps(
            {
                "commit": "a" * 40,
                "documents": [
                    {
                        "path": "docs/company-system/NEXUS_FOCUSED_DELIVERY_PLAN_2026-10-16.md",
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "byte_length": len(raw),
                    }
                ],
            }
        )
    )
    return manifest, hashlib.sha256(manifest.read_bytes()).hexdigest()


def preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PilotConfig:
    from nexus.company import pilot_preview

    monkeypatch.setattr(pilot_preview, "REPOSITORY_ROOT", tmp_path / "repository")
    monkeypatch.setattr(
        pilot_preview,
        "_git_document",
        lambda commit, path: (tmp_path / "repository" / path).read_bytes(),
    )
    manifest, digest = documents(tmp_path)
    return initialize_task(
        tmp_path / "state",
        None,
        profile="local-nexus-owner-preview-v1",
        database_name="nexus_company_test_owner_preview_20261016_1",
        docs_manifest=manifest,
        docs_manifest_sha256=digest,
    )


def test_preview_isolated_database_and_empty_execution_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = preview(tmp_path, monkeypatch)
    assert "nexus_company_test_owner_preview_20261016_1" in config.database_url
    assert config.sdk_receipt is None
    catalog = pilot_catalog(config)
    assert catalog.models.models == () and catalog.tools == ()
    assert catalog.admitted_profiles == frozenset()
    assert not (tmp_path / "state" / "unused-sdk.json").exists()
    for replacement in (
        "nexus_company_test_owner_uat",
        "nexus_company_test_current_v9_negative_v2",
        "postgres",
        "nexus_company_test_owner_preview_x;DROP",
    ):
        url = config.database_url.replace(
            "nexus_company_test_owner_preview_20261016_1", replacement
        )
        with pytest.raises(ValueError, match="exclusive restricted-role"):
            PilotConfig.model_validate(config.model_dump() | {"database_url": url})


async def test_preview_reader_uses_pinned_actual_document_not_synthetic_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.company.brain.access_contracts import ResourceRef
    from nexus.company.brain.sources import SourceRegistration
    from nexus.company.pilot_bootstrap import source_seeds
    from nexus.company.pilot_sources import pilot_sources

    config = preview(tmp_path, monkeypatch)
    seed = source_seeds(config)[0]
    registration = SourceRegistration(
        company_id=config.company_id,
        source_id=seed.source_id,
        resource=ResourceRef(company_id=config.company_id, resource_id=seed.resource_id),
        source_symbol=seed.symbol,
        external_key=seed.key,
    )
    snapshot = await pilot_sources(config).read(registration, seed.revision)
    assert snapshot.raw_bytes.startswith(b"# Nexus\n")
    assert snapshot.revision == "a" * 40 and snapshot.source_event.precision == "unknown"
    path = tmp_path / "repository" / seed.key
    path.write_text("changed")
    with pytest.raises(ValueError, match="document bytes"):
        await pilot_sources(config).read(registration, seed.revision)


def test_preview_create_database_argv_is_exclusive_and_default_uat_cannot_use_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.company import pilot_preview

    config = preview(tmp_path, monkeypatch)
    calls: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...], *, check: bool, capture_output: bool, timeout: int) -> None:
        assert check and capture_output and timeout == 20
        calls.append(argv)

    monkeypatch.setattr(subprocess, "run", run)
    pilot_preview.create_preview_database(config)
    assert calls == [
        (
            "/usr/bin/createdb",
            "-w",
            "-h",
            "/tmp/nexus-release-tests-2026-10-13/socket",
            "-p",
            "55438",
            "-U",
            "santapong",
            "--template=template0",
            "--owner=santapong",
            "--encoding=UTF8",
            "nexus_company_test_owner_preview_20261016_1",
        )
    ]
    from nexus.tests.unit.test_company_pilot_configuration import sdk_receipt

    legacy = initialize_task(tmp_path / "legacy", sdk_receipt(tmp_path))
    with pytest.raises(ValueError, match="fresh local preview"):
        pilot_preview.create_preview_database(legacy)
    assert len(calls) == 1

    def exists(argv: tuple[str, ...], **kwargs: object) -> None:
        calls.append(argv)
        raise subprocess.CalledProcessError(1, argv)

    monkeypatch.setattr(subprocess, "run", exists)
    with pytest.raises(subprocess.CalledProcessError):
        pilot_preview.create_preview_database(config)
    assert len(calls) == 2  # No existing-database reuse/retry or migration fallback.


@pytest.mark.parametrize("fault", ["traversal", "unknown-field", "manifest-hash", "document-hash"])
def test_preview_manifest_denies_unknown_fields_traversal_and_changed_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from nexus.company import pilot_preview

    config = preview(tmp_path, monkeypatch)
    assert config.docs_manifest is not None
    data = json.loads(config.docs_manifest.read_bytes())
    if fault == "traversal":
        data["documents"][0]["path"] = "../../.env"
    elif fault == "unknown-field":
        data["execute"] = True
    elif fault == "document-hash":
        data["documents"][0]["sha256"] = "0" * 64
    else:
        data["commit"] = "b" * 40
    config.docs_manifest.write_text(json.dumps(data))
    if fault != "manifest-hash":
        config = PilotConfig.model_validate(
            config.model_dump()
            | {
                "docs_manifest_sha256": hashlib.sha256(
                    config.docs_manifest.read_bytes()
                ).hexdigest(),
            }
        )
    with pytest.raises(ValueError):
        pilot_preview.preview_documents(config)


def test_actual_alembic_config_preserves_encoded_socket_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alembic.config import Config

    from scripts import company_pilot

    config = preview(tmp_path, monkeypatch)
    assert "%2F" in config.admin_database_url
    observed: list[str] = []
    monkeypatch.setattr(company_pilot, "create_preview_database", lambda selected: None)

    def upgrade(settings: Config, revision: str) -> None:
        assert revision == "head"
        assert settings.get_main_option("sqlalchemy.url") == config.admin_database_url
        observed.append("normal-migrations")

    async def grant(url: str) -> None:
        assert url == config.admin_database_url
        observed.append("app-grant")

    monkeypatch.setattr("alembic.command.upgrade", upgrade)
    monkeypatch.setattr(company_pilot, "grant_app", grant)
    company_pilot.migrate_owned(config)
    assert observed == ["normal-migrations", "app-grant"]
