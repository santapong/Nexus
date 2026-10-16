"""Actual application graph and refusal before credential/storage effects; no SQL or SDK."""

from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.execution.planning_application import (
    compose_planning_application,
    planning_app,
    planning_endpoint_bindings,
)
from nexus.settings import Settings
from nexus.tests.unit.planning_application_fixture import configuration

TEST_SIGNER = "unit-only-planning-application-signer-at-least-thirty-two"


class SuppliedCredential:
    def __init__(self) -> None:
        self.reads = 0

    async def credential(self) -> SecretStr:
        self.reads += 1
        raise AssertionError("Composition must not obtain or mint a worker session")


def application_settings() -> Settings:
    return Settings(
        _env_file=None,
        jwt_algorithm="HS256",
        jwt_secret_key=TEST_SIGNER,
        company_database_url="postgresql+asyncpg://nexus_company_app@/unit_only",
    )


def test_application_shares_concrete_lifecycle_sources_and_reads_without_credential_lookup(
    tmp_path: Path,
) -> None:
    configured = configuration(tmp_path)
    factory = async_sessionmaker[AsyncSession]()
    provider = SuppliedCredential()
    app = compose_planning_application(
        factory, configured, application_settings(), provider, SecretStr(TEST_SIGNER)
    )
    assert provider.reads == 0
    assert not configured.storage.brain_root.exists()
    assert not configured.storage.prepared_root.exists()
    assert not configured.storage.model_evidence_root.exists()
    assert app.runtime.factory is factory
    assert app.runtime.contexts._retriever is app.brain.retriever
    assert app.runtime.contexts._authority is app.runtime.authority
    assert app.management.planning_lifecycle is app.lifecycle
    assert app.planning.lifecycle is app.lifecycle
    assert app.planning.reads.store is app.runtime.prepared
    assert app.runtime.prepared.sources.artifacts is app.runtime.management.artifacts
    assert app.runtime.prepared.sources.freshness is app.runtime.management.freshness
    assert app.management.action_reviews is not None
    assert app.management.action_reviews.planning is app.runtime.prepared
    app.runtime.require_composition()


def test_wrong_http_signer_is_denied_before_private_storage_or_credentials(tmp_path: Path) -> None:
    configured = configuration(tmp_path)
    provider = SuppliedCredential()
    with pytest.raises(ValueError, match="configured HTTP signer"):
        compose_planning_application(
            async_sessionmaker[AsyncSession](),
            configured,
            application_settings(),
            provider,
            SecretStr("a-different-unit-only-signing-key-at-least-thirty-two"),
        )
    assert provider.reads == 0
    assert not configured.storage.brain_root.exists()
    assert not configured.storage.prepared_root.exists()
    assert not configured.storage.model_evidence_root.exists()


def test_conflicting_official_endpoint_identity_is_denied(tmp_path: Path) -> None:
    configured = configuration(tmp_path)
    original = configured.catalog.models.models[0]
    crossed = original.model_copy(
        update={
            "registry_id": "different-registry-id",
            "provider": "google",
            "api_family": "google_generate_content",
        }
    )
    registry = configured.catalog.models.model_copy(update={"models": (original, crossed)})
    catalog = configured.catalog.model_copy(update={"models": registry})
    with pytest.raises(ValueError, match="conflicting official bindings"):
        planning_endpoint_bindings(configured.model_copy(update={"catalog": catalog}))


def test_actual_http_signer_must_match_actor_runtime_before_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.settings import settings

    provider = SuppliedCredential()
    app = compose_planning_application(
        async_sessionmaker[AsyncSession](),
        configuration(tmp_path),
        application_settings(),
        provider,
        SecretStr(TEST_SIGNER),
    )
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    monkeypatch.setattr(
        settings, "jwt_secret_key", "different-http-signing-key-at-least-thirty-two-characters"
    )
    with pytest.raises(ValueError, match="configured HTTP signer"):
        planning_app(app)
    assert provider.reads == 0
