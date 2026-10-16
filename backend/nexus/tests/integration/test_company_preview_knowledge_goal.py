"""Real HTTP knowledge→citation→goal on a fresh explicit local DB, never owner-preview data."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import stat
import subprocess
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.company.brain.retrieval import MaterializedEvidence
from nexus.company.contracts.company import CompanyMandate
from nexus.company.pilot_bootstrap import bootstrap_directory, bootstrap_sources
from nexus.company.pilot_composition import PilotServices, compose_pilot, pilot_app
from nexus.company.pilot_config import PilotConfig
from nexus.company.pilot_preview import REPOSITORY_ROOT, _git_document
from nexus.company.pilot_session_store import PilotCredential, PilotCredentialFile, save_credentials
from nexus.company.pilot_setup import new_config
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import migrate

DATABASE = "nexus_company_test_owner_preview_journey_v1"
DOCUMENTS = (
    "docs/company-system/NEXUS_FOCUSED_DELIVERY_PLAN_2026-10-16.md",
    "docs/company-system/RELEASE_STATUS_2026-10-16.md",
    "docs/company-system/ARCHITECTURE.md",
)


def committed_documents(root: Path) -> tuple[Path, dict[str, bytes], str]:
    """HEAD exists in a shallow checkout; every later read uses this exact immutable revision."""
    revision = (
        subprocess.run(
            (
                "/usr/bin/git",
                "--no-optional-locks",
                "-C",
                str(REPOSITORY_ROOT),
                "rev-parse",
                "HEAD",
            ),
            check=True,
            capture_output=True,
            timeout=5,
        )
        .stdout.decode()
        .strip()
    )
    assert len(revision) == 40
    bodies = {path: _git_document(revision, path) for path in DOCUMENTS}
    manifest = root / "documents.json"
    manifest.write_text(
        json.dumps(
            {
                "commit": revision,
                "documents": [
                    {
                        "path": path,
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "byte_length": len(body),
                    }
                    for path, body in bodies.items()
                ],
            }
        )
    )
    manifest.chmod(0o600)
    return manifest, bodies, revision


@pytest.fixture
async def journey(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[PilotConfig, PilotServices, dict[str, bytes], str, str]]:
    if not settings.company_test_database_url:
        pytest.skip("explicit fresh local preview journey database is not configured")
    url = make_url(settings.company_test_database_url)
    assert url.database == DATABASE and url.username == "santapong" and url.password is None
    assert url.host is None and dict(url.query) == {
        "host": "/tmp/nexus-release-tests-2026-10-13/socket",
        "port": "55438",
    }
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    manifest, bodies, revision = await asyncio.to_thread(committed_documents, root)
    config = new_config(
        root,
        None,
        profile="local-nexus-owner-preview-v1",
        database_name=DATABASE,
        docs_manifest=manifest,
        docs_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
    )
    invitation = secrets.token_urlsafe(32)
    save_credentials(
        config.account_file,
        PilotCredentialFile(
            accounts=(
                PilotCredential(
                    company_id=config.company_id,
                    workspace_id=config.workspace_id,
                    principal_id=config.owner_id,
                    email="journey-test@example.invalid",
                    display_name="Synthetic integration owner",
                    signup_sha256=hashlib.sha256(invitation.encode()).hexdigest(),
                    signup_expires_at=datetime.now(UTC) + timedelta(minutes=15),
                ),
            )
        ),
    )
    assert stat.S_IMODE(config.account_file.stat().st_mode) == 0o600
    # Real session issuance, with an ephemeral process-local test signer restored by pytest.
    monkeypatch.setattr(settings, "jwt_secret_key", secrets.token_urlsafe(48))
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    admin = create_async_engine(url, poolclass=NullPool)
    app_engine = create_async_engine(url.set(username="nexus_company_app"), poolclass=NullPool)
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        services = await asyncio.to_thread(compose_pilot, factory, config)
        await bootstrap_directory(services, config)
        await bootstrap_sources(factory, config)
        yield config, services, bodies, revision, invitation
    finally:
        # Keep this newly isolated DB on success/failure; no destructive shared fixture teardown.
        await app_engine.dispose()
        await admin.dispose()


def frontend_goal_request(
    identity: dict[str, object],
    mandate: dict[str, object],
    evidence_id: str,
    goal_id: str,
) -> dict[str, object]:
    """Mirror the frontend wire literally; >50 lines keeps its exact nested shape visible."""
    company = identity["company_id"]
    return {
        "definition": {
            "schema_version": "nexus.company.management.v1",
            "company_id": company,
            "goal_id": goal_id,
            "title": "Regression: make Nexus knowledge useful",
            "owner_id": identity["principal_id"],
            "mandate": {
                "schema_version": "nexus.company.management.v1",
                "company_id": mandate["company_id"],
                "revision_id": mandate["revision_id"],
                "version": mandate["version"],
                "sha256": mandate["sha256"],
            },
            "metrics": [
                {
                    "schema_version": "nexus.company.management.v1",
                    "company_id": company,
                    "metric_id": "verified-items",
                    "unit": "items",
                    "comparator": "ge",
                    "target": "1",
                    "observation_recipe": None,
                    "baseline": {
                        "kind": "unknown",
                        "reason": "This integration test has no measured baseline",
                        "evidence": [
                            {
                                "schema_version": "nexus.company.brain.v1",
                                "company_id": company,
                                "evidence_id": evidence_id,
                            }
                        ],
                    },
                }
            ],
            "due": {
                "source_time": {
                    "precision": "day",
                    "value": "2026-11-01",
                    "basis": "Owner selected date",
                },
                "actionable_at": None,
                "actionable_basis": None,
            },
        },
        "version": "v1",
        "expected_revision_id": None,
    }


async def test_real_session_knowledge_citation_goal_publish_and_fresh_overview(
    journey: tuple[PilotConfig, PilotServices, dict[str, bytes], str, str],
    tmp_path: Path,
) -> None:
    """Intentionally >50 lines: keep one real auth/citation/goal chain and fresh-client readback."""
    config, services, bodies, revision, invitation = journey
    app = pilot_app(services)
    base = f"/api/v2/companies/{config.company_id}"
    password = secrets.token_urlsafe(24)
    async with AsyncTestClient(app, raise_server_exceptions=True) as client:
        assert (await client.get("/api/v2/company")).status_code == 401
        signup = await client.post(
            "/api/v2/company-session/signup",
            json={
                "email": "journey-test@example.invalid",
                "password": password,
                "invitation": invitation,
            },
        )
        assert signup.status_code == 201  # Never print a token-bearing body on failure.
        login = await client.post(
            "/api/v2/company-session/login",
            json={
                "email": "journey-test@example.invalid",
                "password": password,
            },
        )
        assert login.status_code == 200
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        current = await client.get("/api/v2/company", headers=headers)
        assert current.status_code == 200
        identity = current.json()
        assert identity["principal_id"] == str(config.owner_id)
        # Exact searchRequest wrapper and fields consumed by citationSummaries in the frontend.
        found = await client.post(
            base + "/brain/search",
            headers=headers,
            json={
                "search": {
                    "query": "Nexus",
                    "explicit_evidence_ids": [],
                    "entity_ids": [],
                    "claim_kinds": [],
                    "include_history": False,
                }
            },
        )
        assert found.status_code == 200 and found.json()["handles"]
        handle = found.json()["handles"][0]["handle"]
        record = handle["record"]
        assert handle["company_id"] == record["company_id"] == str(config.company_id)
        assert isinstance(record["evidence_id"], str) and isinstance(record["ingested_at"], str)
        assert isinstance(record["source_event"], dict) and isinstance(record["raw_span"], dict)
        assert record["artifact"]["revision"] == revision
        evidence = await client.get(
            base + "/brain/evidence/" + record["evidence_id"], headers=headers
        )
        assert evidence.status_code == 200
        material = MaterializedEvidence.model_validate_json(evidence.content)
        raw = bodies[material.external_key]
        span = material.record.raw_span
        assert material.source_state == "current"
        assert material.record.artifact.sha256 == hashlib.sha256(raw).hexdigest()
        assert material.text.encode() == raw[span.start_byte : span.end_byte]
        mandate = CompanyMandate(
            company_id=config.company_id,
            owner_id=config.owner_id,
            version="journey-v1",
            purpose="Isolated Nexus public HTTP integration regression",
            goals=(),
        )
        admitted = await client.post(
            base + "/management/mandate",
            headers=headers,
            json={
                "mandate": mandate.model_dump(mode="json"),
                "expected_revision_id": None,
            },
        )
        assert admitted.status_code == 200
        company = await client.get(base + "/management/company", headers=headers)
        assert company.status_code == 200
        goal_id = str(uuid4())
        body = frontend_goal_request(
            identity,
            company.json()["mandate"]["revision"],
            record["evidence_id"],
            goal_id,
        )
        published = await client.post(base + "/management/goals", headers=headers, json=body)
        assert published.status_code == 200
        created = published.json()
        assert created["goal_id"] == goal_id and created["recorded_by"] == str(config.owner_id)
    async with AsyncTestClient(app, raise_server_exceptions=True) as fresh_client:
        overview = await fresh_client.get(base + "/management/company", headers=headers)
        assert overview.status_code == 200
        goals = overview.json()["goals"]
        assert len(goals) == 1 and goals[0]["reference"]["goal_id"] == goal_id
        assert goals[0]["reference"]["revision_id"] == created["revision_id"]
        baseline = goals[0]["metrics"][0]["baseline"]
        assert baseline["kind"] == "unknown"
        assert baseline["evidence"][0]["evidence_id"] == record["evidence_id"]
        assert goals[0]["due"]["source_time"]["precision"] == "day"
        assert goals[0]["due"]["actionable_at"] is None and overview.json()["plans"] == []
    # Safe retained result: no password, invitation, JWT, request headers or session response body.
    (tmp_path / "journey-result.json").write_text(
        json.dumps(
            {
                "scope": "Real isolated API/PG regression; not owner/browser acceptance",
                "company_id": str(config.company_id),
                "source_commit": revision,
                "evidence_id": record["evidence_id"],
                "artifact_sha256": material.record.artifact.sha256,
                "goal_id": goal_id,
                "goal_revision_id": created["revision_id"],
                "public_http_statuses": {
                    "signup": signup.status_code,
                    "login": login.status_code,
                    "identity": current.status_code,
                    "search": found.status_code,
                    "evidence": evidence.status_code,
                    "mandate": admitted.status_code,
                    "company_before": company.status_code,
                    "goal": published.status_code,
                    "fresh_overview": overview.status_code,
                },
                "baseline": "unknown",
                "actionable_at": None,
                "source_reader": "actual_git_document",
            },
            indent=2,
        )
        + "\n"
    )
