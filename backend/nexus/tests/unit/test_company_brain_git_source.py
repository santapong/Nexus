"""Immutable nominated Git reads use bounded argv and never import dirty working files."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from uuid import UUID

import pytest

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import SourceTime
from nexus.company.brain.git_source import CommittedGitSourceReader, GitSnapshotSpec
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.brain.sources import SourceRegistration


@pytest.fixture
def nominated(tmp_path: Path) -> tuple[Path, GitSnapshotSpec, bytes]:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
    raw = ("Snapshot ไทย 🚀\n" * 12000).encode()
    (repository / "README.md").write_bytes(raw)
    subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Nexus Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "test fixture",
        ],
        cwd=repository,
        check=True,
    )

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repository).decode().strip()

    spec = GitSnapshotSpec(
        company_id=UUID(int=1),
        source_id=UUID(int=2),
        source_symbol="fixture.git.v1",
        external_key="readme",
        path="README.md",
        commit=git("rev-parse", "HEAD"),
        git_blob=git("rev-parse", "HEAD:README.md"),
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
        source_event=SourceTime(
            precision="instant",
            value=git("show", "-s", "--format=%cI", "HEAD"),
            basis="immutable fixture Git commit timestamp",
        ),
    )
    (repository / "README.md").write_text("Concurrent dirty edits must stay out of Nexus")
    return repository, spec, raw


def source(spec: GitSnapshotSpec) -> SourceRegistration:
    return SourceRegistration(
        company_id=spec.company_id,
        source_id=spec.source_id,
        source_symbol=spec.source_symbol,
        external_key=spec.external_key,
        resource=ResourceRef(company_id=spec.company_id, resource_id=UUID(int=3)),
    )


async def test_large_immutable_blob_is_complete_and_dirty_checkout_is_excluded(
    nominated: tuple[Path, GitSnapshotSpec, bytes],
) -> None:
    repository, spec, raw = nominated
    result = await CommittedGitSourceReader(repository, (spec,)).read(source(spec), spec.commit)
    assert result.raw_bytes == raw
    assert result.source_event == spec.source_event
    assert result.revision == spec.commit


async def test_oversized_pipe_is_denied_and_owned_child_cleanup_finishes(
    nominated: tuple[Path, GitSnapshotSpec, bytes],
) -> None:
    import asyncio

    repository, spec, _ = nominated
    reader = CommittedGitSourceReader(repository, (spec,))
    async with asyncio.timeout(3):
        with pytest.raises(BrainDeniedError, match="read bound"):
            await reader._git("cat-file", "blob", spec.git_blob, limit=64)


@pytest.mark.parametrize("change", ["revision", "company", "source", "key", "hash"])
async def test_request_cannot_choose_another_source_ref_or_content(
    nominated: tuple[Path, GitSnapshotSpec, bytes],
    change: str,
) -> None:
    repository, spec, _ = nominated
    selection = source(spec)
    revision = spec.commit
    if change == "revision":
        revision = "HEAD"
    elif change == "company":
        selection = selection.model_copy(update={"company_id": UUID(int=99)})
    elif change == "source":
        selection = selection.model_copy(update={"source_id": UUID(int=99)})
    elif change == "key":
        selection = selection.model_copy(update={"external_key": "../../private"})
    else:
        spec = spec.model_copy(update={"sha256": "0" * 64})
    with pytest.raises(BrainDeniedError):
        await CommittedGitSourceReader(repository, (spec,)).read(selection, revision)


@pytest.mark.parametrize("path", ["../secret", "/secret", ".git/config", "a\\b", "a/./b"])
def test_source_spec_requires_an_exact_nominated_regular_path(path: str) -> None:
    with pytest.raises(ValueError):
        GitSnapshotSpec(
            company_id=UUID(int=1),
            source_id=UUID(int=2),
            source_symbol="fixture.git.v1",
            external_key="readme",
            path=path,
            commit="1" * 40,
            git_blob="2" * 40,
            sha256="3" * 64,
            byte_length=1,
            source_event=SourceTime(
                precision="instant",
                value="2026-10-14T00:00:00Z",
                basis="fixture",
            ),
        )
