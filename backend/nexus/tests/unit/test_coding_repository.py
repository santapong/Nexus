"""Real committed Git acquisition plus finite retained-read boundary checks."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.builder.contained_query import clock_us
from nexus.builder.contracts import RepositoryPin
from nexus.company.brain.base import BrainReadScope, SourceTime
from nexus.company.brain.git_source import GitSnapshotSpec
from nexus.company.management.coding_repository import (
    CodingRepositoryReader,
    CodingRepositorySelection,
)
from nexus.tests.unit.test_native_builder_snapshot import git


@pytest.fixture
def nominated(tmp_path: Path) -> tuple[Path, CodingRepositorySelection, bytes]:
    repository = tmp_path / "repository"
    repository.mkdir(mode=0o700)
    git(repository, "init", "-q")
    raw = "def answer():\n    return 'Nexus ไทย'\n".encode()
    (repository / "answer.py").write_bytes(raw)
    git(repository, "add", "answer.py")
    git(
        repository,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "coding source",
    )
    commit = git(repository, "rev-parse", "HEAD").decode().strip()
    archive = git(repository, "archive", "--format=tar", commit)
    spec = GitSnapshotSpec(
        company_id=UUID(int=1),
        source_id=UUID(int=2),
        source_symbol="coding.fixture",
        external_key="answer",
        path="answer.py",
        commit=commit,
        git_blob=git(repository, "rev-parse", "HEAD:answer.py").decode().strip(),
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
        source_event=SourceTime(
            precision="instant",
            value=git(repository, "show", "-s", "--format=%cI", commit).decode().strip(),
            basis="Actual local fixture commit",
        ),
    )
    selected = CodingRepositorySelection(
        company_id=spec.company_id,
        source=RepositoryPin(
            repository_symbol="nexus.fixture",
            commit=commit,
            tree=git(repository, "rev-parse", "HEAD^{tree}").decode().strip(),
            archive_sha256=hashlib.sha256(archive).hexdigest(),
        ),
        files=(spec,),
        allowed_write_paths=(spec.path,),
    )
    (repository / "answer.py").write_text("dirty content must not enter the prompt")
    (repository / "private-untracked").write_text("not committed")
    return repository, selected, raw


def scope() -> BrainReadScope:
    return BrainReadScope(
        company_id=UUID(int=1),
        workspace_id=UUID(int=3),
        principal_id=UUID(int=4),
        operation_id=UUID(int=5),
        trace_id=UUID(int=6),
        task_id=UUID(int=7),
        task_trace_id=UUID(int=8),
        actor_id=UUID(int=4),
    )


async def test_actual_archive_and_selected_code_are_exact_not_dirty(
    nominated: tuple[Path, CodingRepositorySelection, bytes],
) -> None:
    repository, selected, raw = nominated
    reader = CodingRepositoryReader(repository, selected)
    original_end = clock_us() + 10_000_000
    result = await reader.read(scope(), end_us=original_end)
    assert result.value.source == selected.source
    assert result.value.files[0].text.encode() == raw
    assert result.value.files[0].metadata.sha256 == selected.files[0].sha256
    assert result.value.selection_sha256 == reader.selection_sha256
    assert tuple(row.metadata.path for row in result.value.files) == ("answer.py",)
    assert result.read_end_us == original_end
    assert not reader.pending_owners()


@pytest.mark.parametrize("field", ["commit", "tree", "archive_sha256"])
async def test_crossed_repository_pin_never_returns_material(
    nominated: tuple[Path, CodingRepositorySelection, bytes],
    field: str,
) -> None:
    repository, selected, _ = nominated
    changed = selected.source.model_copy(
        update={field: "f" * (64 if field == "archive_sha256" else 40)}
    )
    selected = selected.model_copy(update={"source": changed})
    with pytest.raises(ValueError):
        await CodingRepositoryReader(repository, selected).read(
            scope(), end_us=clock_us() + 10_000_000
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("sha256", "f" * 64),
        ("git_blob", "f" * 40),
        ("byte_length", 1),
        ("path", "missing.py"),
        ("company_id", UUID(int=99)),
    ],
)
async def test_selected_file_nomination_cannot_forge_actual_archive_bytes(
    nominated: tuple[Path, CodingRepositorySelection, bytes],
    field: str,
    value: object,
) -> None:
    repository, selected, _ = nominated
    selected = selected.model_copy(
        update={"files": (selected.files[0].model_copy(update={field: value}),)}
    )
    with pytest.raises(ValueError):
        await CodingRepositoryReader(repository, selected).read(
            scope(), end_us=clock_us() + 10_000_000
        )


async def test_expired_or_foreign_scope_stops_before_actual_archive_read(
    nominated: tuple[Path, CodingRepositorySelection, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.company.management import coding_repository as module

    repository, selected, _ = nominated
    archive = AsyncMock(side_effect=AssertionError("Expired/foreign read performed Git IO"))
    monkeypatch.setattr(module, "committed_archive", archive)
    reader = CodingRepositoryReader(repository, selected)
    with pytest.raises((ValueError, TimeoutError)):
        await reader.read(scope(), end_us=clock_us() - 1)
    with pytest.raises(ValueError):
        await reader.read(
            scope().model_copy(update={"company_id": UUID(int=99)}), end_us=clock_us() + 1_000_000
        )
    archive.assert_not_called()


@pytest.mark.parametrize("stop", ["cancel", "timeout", "replace"])
async def test_actual_archive_owner_settles_without_late_positive_adoption(
    nominated: tuple[Path, CodingRepositorySelection, bytes],
    monkeypatch: pytest.MonkeyPatch,
    stop: str,
) -> None:
    from nexus.company.management import coding_repository as module

    repository, selected, _ = nominated
    raw = git(repository, "archive", "--format=tar", selected.source.commit)
    entered, finish = asyncio.Event(), asyncio.Event()

    async def blocked(*args: object) -> bytes:
        entered.set()
        await finish.wait()
        return raw

    monkeypatch.setattr(module, "committed_archive", blocked)
    reader = CodingRepositoryReader(repository, selected)
    driver = asyncio.create_task(
        reader.read(scope(), end_us=clock_us() + (20_000 if stop == "timeout" else 1_000_000))
    )
    await entered.wait()
    if stop == "replace":
        reader._selection = selected.model_copy(update={"allowed_write_paths": ()})
        finish.set()
    elif stop == "cancel":
        driver.cancel()
    with pytest.raises((asyncio.CancelledError, TimeoutError, ValueError)):
        await driver
    if stop != "replace":
        assert reader.pending_owners()
    finish.set()
    await asyncio.gather(*reader.pending_owners(), return_exceptions=True)
    assert not reader.pending_owners()
    with pytest.raises(ValueError):
        await reader.read(scope(), end_us=clock_us() + 1_000_000)


async def test_cancelled_materialization_keeps_actual_thread_owner_until_settled(
    nominated: tuple[Path, CodingRepositorySelection, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.company.management import coding_repository as module

    repository, selected, _ = nominated
    entered, finish = threading.Event(), threading.Event()
    original = module._material

    def blocked(
        raw: bytes, nomination: CodingRepositorySelection
    ) -> module.CodingRepositoryMaterial:
        entered.set()
        assert finish.wait(3)
        return original(raw, nomination)

    monkeypatch.setattr(module, "_material", blocked)
    reader = CodingRepositoryReader(repository, selected)
    driver = asyncio.create_task(reader.read(scope(), end_us=clock_us() + 2_000_000))
    try:
        async with asyncio.timeout(2):
            while not entered.is_set():
                await asyncio.sleep(0.001)
        driver.cancel()
        with pytest.raises(asyncio.CancelledError):
            await driver
        assert reader.pending_owners()
    finally:
        finish.set()
        await asyncio.gather(*reader.pending_owners(), return_exceptions=True)
    assert not reader.pending_owners()
    with pytest.raises(ValueError):
        await reader.read(scope(), end_us=clock_us() + 1_000_000)
