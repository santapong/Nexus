"""Actual local committed-source reads exclude dirty files and reject unsafe archive metadata."""

import asyncio
import hashlib
import io
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from nexus.builder.contracts import RepositoryPin
from nexus.builder.snapshot import committed_archive, extract_source, git_bytes, private_directory


def git(repository: Path, *arguments: str) -> bytes:
    return subprocess.check_output(
        [
            "/usr/bin/git",
            "--no-replace-objects",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "-C",
            str(repository),
            *arguments,
        ],
        env={
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        },
        stderr=subprocess.DEVNULL,
    )


async def test_actual_git_snapshot_uses_exact_commit_not_dirty_working_tree(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init", "-q")
    (repository / "answer.txt").write_text("actual committed source")
    git(repository, "add", "answer.txt")
    git(
        repository,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    commit = git(repository, "rev-parse", "HEAD").decode().strip()
    tree = git(repository, "rev-parse", "HEAD^{tree}").decode().strip()
    raw = git(repository, "archive", "--format=tar", commit)
    pin = RepositoryPin(
        repository_symbol="fixture",
        commit=commit,
        tree=tree,
        archive_sha256=hashlib.sha256(raw).hexdigest(),
    )
    (repository / "answer.txt").write_text("unapproved dirty content")
    (repository / "untracked-private.txt").write_text("not committed")
    exact = await committed_archive(repository, pin)
    destination = tmp_path / "job-source"
    manifest = extract_source(exact, pin, destination)
    assert tuple(row.path for row in manifest) == ("answer.txt",)
    assert (destination / "answer.txt").read_text() == "actual committed source"
    with pytest.raises(ValueError):
        await committed_archive(repository, pin.model_copy(update={"tree": "1" * 40}))
    with pytest.raises(ValueError):
        extract_source(exact, pin, destination)
    # Bounded overflow must drain a killed Git PIPE rather than hanging during cleanup.
    with pytest.raises(ValueError):
        await asyncio.wait_for(
            git_bytes(repository, "archive", "--format=tar", commit, limit=1), timeout=3
        )


@pytest.mark.parametrize(
    "name,kind",
    [
        ("../escape", tarfile.REGTYPE),
        ("/absolute", tarfile.REGTYPE),
        ("link", tarfile.SYMTYPE),
        ("hardlink", tarfile.LNKTYPE),
        ("fifo", tarfile.FIFOTYPE),
        (".env", tarfile.REGTYPE),
        (".git/config", tarfile.REGTYPE),
    ],
)
def test_unsafe_archive_denied_before_destination_creation(
    tmp_path: Path, name: str, kind: bytes
) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        entry = tarfile.TarInfo(name)
        entry.type = kind
        entry.linkname = "../private" if kind in {tarfile.SYMTYPE, tarfile.LNKTYPE} else ""
        archive.addfile(entry, io.BytesIO(b""))
    raw = buffer.getvalue()
    pin = RepositoryPin(
        repository_symbol="fixture",
        commit="1" * 40,
        tree="2" * 40,
        archive_sha256=hashlib.sha256(raw).hexdigest(),
    )
    destination = tmp_path / "job-source"
    with pytest.raises(ValueError):
        extract_source(raw, pin, destination)
    assert not destination.exists()


def test_real_world_readable_job_directory_is_unqualified(tmp_path: Path) -> None:
    root = tmp_path / "unsafe-job"
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(ValueError, match="private ownership/mode"):
            private_directory(descriptor)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("verb", ["init", "fetch", "push", "checkout"])
async def test_git_mutation_verbs_never_launch(
    tmp_path: Path, verb: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("A disallowed Git operation reached the process boundary")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    with pytest.raises(ValueError, match="only exact committed"):
        await git_bytes(tmp_path, verb, limit=64)
