"""Closed local preview inputs and normal public mandate; no execution service."""

from __future__ import annotations

import asyncio
import hashlib
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Self
from uuid import uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nexus.company.brain.base import SourceTime
from nexus.company.brain.source_registry import SourcePolicy, SourceRegistry, SourceSnapshot
from nexus.company.brain.sources import SourceRegistration
from nexus.company.contracts.company import CompanyMandate
from nexus.company.management.governance import MandateRevision
from nexus.company.pilot_config import PREVIEW_PROFILE, PilotConfig, preview_database_name

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class PreviewDocumentPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str = Field(pattern=r"^(README\.md|docs/company-system/[A-Z0-9_-]+\.md)$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_length: int = Field(gt=0, le=131072, strict=True)


class PreviewManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    documents: tuple[PreviewDocumentPin, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if (
            len({v.path for v in self.documents}) != len(self.documents)
            or sum(v.byte_length for v in self.documents) > 262144
        ):
            raise ValueError("Preview documents must be a small distinct pinned allowlist")
        return self


@dataclass(frozen=True)
class PreviewDocument:
    pin: PreviewDocumentPin
    commit: str
    text: str


def _bounded_file(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("Preview input must be an ordinary file")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError("Preview input exceeds its byte bound")
    return raw


def preview_documents(config: PilotConfig) -> tuple[PreviewDocument, ...]:
    if config.profile != PREVIEW_PROFILE or config.docs_manifest is None:
        raise ValueError("Pinned Nexus preview document manifest is required")
    raw = _bounded_file(config.docs_manifest, 16384)
    if hashlib.sha256(raw).hexdigest() != config.docs_manifest_sha256:
        raise ValueError("Preview document manifest SHA differs")
    manifest = PreviewManifest.model_validate_json(raw)
    result = []
    for pin in manifest.documents:
        body = _git_document(manifest.commit, pin.path)
        if len(body) != pin.byte_length or hashlib.sha256(body).hexdigest() != pin.sha256:
            raise ValueError("Preview document bytes differ from the committed allowlist")
        text = body.decode("utf-8", "strict")
        if "\x00" in text:
            raise ValueError("Preview document bytes contain NUL")
        result.append(PreviewDocument(pin, manifest.commit, text))
    return tuple(result)


def _git_document(commit: str, path: str) -> bytes:
    """Read the exact committed public document, independent of working-tree edits."""
    result = subprocess.run(
        (
            "/usr/bin/git",
            "--no-optional-locks",
            "-C",
            str(REPOSITORY_ROOT),
            "show",
            f"{commit}:{path}",
        ),
        check=True,
        capture_output=True,
        timeout=5,
    )
    if not result.stdout or len(result.stdout) > 131072:
        raise ValueError("Preview document bytes exceed their bound")
    return result.stdout


def document_symbol(index: int) -> str:
    return f"nexus.preview.document.{index}.v1"


class PreviewSourceReader:
    def __init__(self, config: PilotConfig) -> None:
        self.config = config

    async def read(self, source: SourceRegistration, revision: str) -> SourceSnapshot:
        documents = await asyncio.to_thread(preview_documents, self.config)
        for index, document in enumerate(documents):
            if (
                source.company_id == self.config.company_id
                and source.source_id == uuid5(self.config.public_source_id, document.pin.path)
                and source.source_symbol == document_symbol(index)
                and source.external_key == document.pin.path
                and revision == document.commit
            ):
                return SourceSnapshot(
                    company_id=self.config.company_id,
                    source_id=source.source_id,
                    source_symbol=source.source_symbol,
                    external_key=source.external_key,
                    revision=revision,
                    raw_bytes=document.text.encode(),
                    source_event=SourceTime(
                        precision="unknown",
                        value=None,
                        basis="Pinned Nexus repository revision; source event time not supplied",
                    ),
                )
        raise ValueError("Exact pinned Nexus preview document is unavailable")


def preview_registry(config: PilotConfig) -> SourceRegistry:
    documents = preview_documents(config)
    return SourceRegistry(
        tuple(
            SourcePolicy(
                source_symbol=document_symbol(index),
                authority_profile="nexus.pinned-docs.v1",
                data_classification="internal",
                media_type="text/markdown",
                parser_version="utf8-identity-v1",
                chunker_version="utf8-sections-v1",
                search_config="simple",
                freshness_seconds=None,
                allowed_external_keys=frozenset({document.pin.path}),
                max_bytes=131072,
            )
            for index, document in enumerate(documents)
        ),
        PreviewSourceReader(config),
    )


def create_preview_database(config: PilotConfig) -> None:
    """Exclusive createdb fails on any existing name; never migrates an existing preview."""
    if config.profile != PREVIEW_PROFILE:
        raise ValueError("Only a fresh local preview may create a database")
    from sqlalchemy.engine import make_url

    name = preview_database_name(make_url(config.database_url).database or "")
    preview_documents(config)
    subprocess.run(
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
            name,
        ),
        check=True,
        capture_output=True,
        timeout=20,
    )


async def publish_preview_mandate(controls: object, config: PilotConfig) -> MandateRevision:
    from nexus.company.management.control_store import ManagementControlStore

    if not isinstance(controls, ManagementControlStore) or config.profile != PREVIEW_PROFILE:
        raise ValueError("Preview requires the actual owner mandate service")
    return await controls.publish_mandate(
        config.control(),
        config.identity(),
        CompanyMandate(
            company_id=config.company_id,
            owner_id=config.owner_id,
            version="nexus-local-preview-v1",
            oversight="supervised",
            goals=(),
            purpose="Improve Nexus under owner supervision; execution and external effects are off",
        ),
        expected_revision_id=None,
    )
