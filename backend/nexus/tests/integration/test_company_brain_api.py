"""Real signed HTTP/read-only Brain materialization through restricted PostgreSQL."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.blob_store import BlobReader
from nexus.company.brain.context import AssembledContext
from nexus.company.brain.models import BrainEntity, BrainEntityEvidence, BrainEntityRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.harness.journal_models import CostHold, WorkBudget
from nexus.tests.brain_api_support import actual_services, brain_app
from nexus.tests.brain_api_support import brain_api_factory as brain_api_factory
from nexus.tests.brain_sdk_capture import capture_context
from nexus.tests.integration.test_company_api import headers
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, SOURCE, owner_scope
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    TASK,
    TRACE,
    control,
    work,
)
from nexus.tests.integration.test_company_execution_store import identity

BASE = f"/api/v2/companies/{COMPANY}/brain"
RAW = b"Authorized API content with attachment sentinel U1 and prerequisite W1.\n"


class RevokingReader:
    """Revoke after the initial authorized selection and before final HTTP publication."""

    def __init__(self, reader: BlobReader, factory: async_sessionmaker[AsyncSession]) -> None:
        self.reader, self.factory = reader, factory

    async def read(self, reference: ArtifactRevisionRef) -> bytes:
        raw = await self.reader.read(reference)
        await ResourceAccessStore(self.factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                principal_id=ACTOR,
                active=False,
                expires_at=None,
                expected_generation=1,
            ),
        )
        return raw


@pytest.mark.parametrize("kind", ["evidence", "artifact"])
async def test_http_revocation_during_blob_read_never_publishes_payload(
    brain_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path, kind: str
) -> None:
    services = await actual_services(brain_api_factory, tmp_path, RAW)
    async with AsyncTestClient(brain_app(services)) as client:
        found = await client.post(
            BASE + "/search", headers=headers(), json={"search": {"query": "Authorized"}}
        )
        handle = found.json()["handles"][0]["handle"]
        services.retriever.blobs = RevokingReader(services.retriever.blobs, brain_api_factory)
        path = (
            f"/evidence/{handle['evidence_id']}"
            if kind == "evidence"
            else f"/artifacts/{handle['record']['artifact']['artifact_revision_id']}"
        )
        denied = await client.get(BASE + path, headers=headers())
        assert denied.status_code == 403 and "sentinel" not in denied.text


async def test_real_http_search_evidence_artifact_and_freshness(
    brain_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    services = await actual_services(brain_api_factory, tmp_path, RAW)
    async with AsyncTestClient(brain_app(services)) as client:
        search = await client.post(
            BASE + "/search", headers=headers(), json={"search": {"query": "Authorized"}}
        )
        assert search.status_code == 200 and len(search.json()["handles"]) == 1
        handle = search.json()["handles"][0]["handle"]
        assert "text" not in handle
        evidence = await client.get(BASE + f"/evidence/{handle['evidence_id']}", headers=headers())
        assert evidence.status_code == 200 and evidence.json()["text"] == RAW.decode()
        artifact_id = handle["record"]["artifact"]["artifact_revision_id"]
        artifact = await client.get(BASE + f"/artifacts/{artifact_id}", headers=headers())
        assert artifact.status_code == 200 and artifact.json()["text"] == RAW.decode()
        assert artifact.json()["span_sha256"] == hashlib.sha256(RAW).hexdigest()
        freshness = await client.get(BASE + f"/sources/{SOURCE}/freshness", headers=headers())
        assert freshness.status_code == 200 and freshness.json()["availability"] == "available"
        assert freshness.json()["source_id"] == str(SOURCE)


async def test_http_artifact_reads_real_full_blob_with_server_bound_and_continuation(
    brain_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    raw = ("ไทย API content\n" * 2000).encode()
    services = await actual_services(brain_api_factory, tmp_path, raw)
    async with AsyncTestClient(brain_app(services)) as client:
        search = await client.post(
            BASE + "/search", headers=headers(), json={"search": {"query": "content"}}
        )
        handle = search.json()["handles"][0]["handle"]
        path = BASE + f"/artifacts/{handle['record']['artifact']['artifact_revision_id']}"
        first = await client.get(path, params={"max_bytes": "999999"}, headers=headers())
        assert first.status_code == 200
        data = first.json()
        assert len(data["text"].encode()) <= 16384 and data["has_more"] is True
        assert data["artifact"]["byte_length"] == len(raw)
        assert data["artifact"]["sha256"] == hashlib.sha256(raw).hexdigest()
        offset = data["span"]["end_byte"]
        second = await client.get(path, params={"start_byte": offset}, headers=headers())
        assert second.status_code == 200 and second.json()["span"]["start_byte"] == offset
        assert raw[:offset] == data["text"].encode()
        invalid = await client.get(path, params={"start_byte": -1}, headers=headers())
        assert invalid.status_code == 422


@pytest.mark.parametrize("kind", ["evidence", "artifact", "freshness", "context", "search"])
async def test_http_revoked_grant_denies_every_read_payload(
    brain_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path, kind: str
) -> None:
    services = await actual_services(brain_api_factory, tmp_path, RAW)
    async with AsyncTestClient(brain_app(services)) as client:
        found = await client.post(
            BASE + "/search", headers=headers(), json={"search": {"query": "Authorized"}}
        )
        handle = found.json()["handles"][0]["handle"]
        await ResourceAccessStore(brain_api_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                principal_id=ACTOR,
                active=False,
                expires_at=None,
                expected_generation=1,
            ),
        )
        if kind == "context":
            denied = await client.post(
                BASE + "/context", headers=headers(), json={"attachments": [handle["evidence_id"]]}
            )
        elif kind == "search":
            denied = await client.post(
                BASE + "/search", headers=headers(), json={"search": {"query": "Authorized"}}
            )
            assert denied.status_code == 200 and denied.json()["handles"] == []
            return
        else:
            paths = {
                "evidence": f"/evidence/{handle['evidence_id']}",
                "artifact": f"/artifacts/{handle['record']['artifact']['artifact_revision_id']}",
                "freshness": f"/sources/{SOURCE}/freshness",
            }
            denied = await client.get(BASE + paths[kind], headers=headers())
        assert denied.status_code == 403 and RAW.decode() not in denied.text


async def test_real_context_reads_attachment_workspace_and_mints_no_allowance(
    brain_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    services = await actual_services(brain_api_factory, tmp_path, RAW)
    async with AsyncTestClient(brain_app(services)) as client:
        found = await client.post(
            BASE + "/search", headers=headers(), json={"search": {"query": "Authorized"}}
        )
        key = found.json()["handles"][0]["handle"]["evidence_id"]
        context = await client.post(
            BASE + "/context",
            headers=headers(),
            json={"attachments": [key], "workspace_files": [key]},
        )
        assert context.status_code == 200
        data = json.loads(context.json()["input_text"])
        assert data["untrusted_source_data"][0]["text"] == RAW.decode()
        captured = await capture_context(AssembledContext.model_validate_json(context.text))
        assert "sentinel U1" in captured.request_json and "prerequisite W1" in captured.request_json
        manifest = context.json()["manifest"]
        assert manifest["task_id"] is None and manifest["token_qualification"] == "unavailable"
    async with brain_api_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(WorkBudget)) == 0
        assert await session.scalar(select(func.count()).select_from(CostHold)) == 0


async def test_http_current_entity_materializes_all_evidence_and_final_grants(
    brain_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    services = await actual_services(brain_api_factory, tmp_path, RAW)
    async with AsyncTestClient(brain_app(services)) as client:
        found = await client.post(
            BASE + "/search", headers=headers(), json={"search": {"query": "Authorized"}}
        )
        key = UUID(found.json()["handles"][0]["handle"]["evidence_id"])
        await _seed_entity(brain_api_factory, key)
        result = await client.get(BASE + f"/entities/{UUID(int=2000)}", headers=headers())
        assert result.status_code == 200 and result.json()["content"]["label"] == "API project"
        assert result.json()["evidence"][0]["evidence_id"] == str(key)


async def test_actual_registered_work_binding_keeps_actor_and_owner_audit_distinct(
    brain_api_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    services = await actual_services(brain_api_factory, tmp_path, RAW)
    assert isinstance(services.directory, PersistentCompanyDirectory)
    await services.directory.register_work(work(), control())
    body = {"task_id": str(TASK), "task_trace_id": str(TRACE), "search": {"query": "Authorized"}}
    async with AsyncTestClient(brain_app(services)) as client:
        bound = await client.post(BASE + "/context", headers=headers(OWNER), json=body)
        assert bound.status_code == 200
        manifest = bound.json()["manifest"]
        assert manifest["principal_id"] == str(OWNER) and manifest["actor_id"] == str(ACTOR)
        assert manifest["task_id"] == str(TASK) and manifest["task_trace_id"] == str(TRACE)
        assert manifest["operation_id"] != str(TASK) and manifest["trace_id"] != str(TRACE)
        wrong = await client.post(
            BASE + "/context", headers=headers(), json=body | {"task_trace_id": str(UUID(int=99))}
        )
        assert wrong.status_code == 403
        await services.directory.set_work_active(control(), task_id=TASK, active=False)
        owner = await client.post(BASE + "/context", headers=headers(OWNER), json=body)
        actor = await client.post(BASE + "/context", headers=headers(), json=body)
        assert owner.status_code == 200 and actor.status_code == 403


async def _seed_entity(factory: async_sessionmaker[AsyncSession], evidence_id: UUID) -> None:
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        entity = BrainEntity(
            company_id=COMPANY,
            entity_id=UUID(int=2000),
            resource_id=RESOURCE,
            kind="Project",
            current_revision_id=None,
        )
        session.add(entity)
        await session.flush()
        session.add(
            BrainEntityRevision(
                company_id=COMPANY,
                entity_revision_id=UUID(int=2001),
                entity_id=UUID(int=2000),
                kind="Project",
                revision="1",
                content_json='{"kind":"Project","label":"API project"}',
                source_event_json='{"precision":"unknown","value":null,"basis":"fixture"}',
                ingested_at=func.clock_timestamp(),
                origin="source",
                status="source_report",
            )
        )
        await session.flush()
        entity.current_revision_id = UUID(int=2001)
        session.add(
            BrainEntityEvidence(
                company_id=COMPANY, entity_revision_id=UUID(int=2001), evidence_id=evidence_id
            )
        )
