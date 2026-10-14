"""Stage only reviewed generated public source bytes and a genuine harmless two-file Git patch."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from nexus.builder.contracts import RepositoryPin
from nexus.builder.csv_behavior_wrapper import mapping_sha256
from nexus.builder.csv_report_contracts import CsvRegressionPins
from nexus.builder.node_v4_assets import csv_wrapper_sha256
from nexus.tests.csv_native_scope import PLAN, PUBLIC, require_root

WRITE_PATHS = ("packages/shared/src/csv/csv.test.ts", "packages/shared/src/csv/index.ts")
PROPOSAL_SHA = "4eeac033e161421d050e0812e55d7b3776325b69ab21e31b5d0a3c315a2ea4a0"


@dataclass(frozen=True)
class CsvNativeSource:
    repository: Path
    pin: RepositoryPin
    patch: bytes
    csv: CsvRegressionPins


def reviewed_sources() -> tuple[dict[str, bytes], dict[str, bytes]]:
    """Local fixture file maps are data only; they never become an execution protocol or grant."""
    raw = (PLAN / "NATIVE_CSV_PG_PROPOSAL_v2.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROPOSAL_SHA:
        raise ValueError("CSV native reviewed proposal bytes changed")
    packet = json.loads(raw)
    trees = []
    for phase in ("baseline", "post"):
        hashes = packet["public_source"][phase + "_files"]
        rows = {
            name: ordinary_bytes(PUBLIC / "source" / phase / name, 1048576, digest)
            for name, digest in hashes.items()
        }
        if len(rows) != 39 or sum(map(len, rows.values())) > 16777216:
            raise ValueError("CSV native generated source inventory exceeds its exact bound")
        trees.append(rows)
    if tuple(sorted(name for name in trees[0] if trees[0][name] != trees[1][name])) != WRITE_PATHS:
        raise ValueError("CSV native source delta differs from exact two-file patch")
    return trees[0], trees[1]


def ordinary_bytes(path: Path, maximum: int, digest: str) -> bytes:
    """Read a pinned ordinary owned public file with bounded no-follow descriptor semantics."""
    if path.resolve(strict=True) != path:
        raise ValueError("CSV native public source namespace changed")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or not 0 < info.st_size <= maximum
        ):
            raise ValueError("CSV native public input exceeds ordinary ownership/byte bounds")
        raw = stream.read(maximum + 1)
    if len(raw) != info.st_size or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("CSV native public input bytes differ from reviewed pin")
    return raw


def stage_source(root: Path) -> CsvNativeSource:
    require_root(root, existing=True)
    before, after = reviewed_sources()
    repository = root / "harmless-csv-repository"
    repository.mkdir(mode=0o700, exist_ok=False)
    for name, raw in before.items():
        path = repository / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o600)
    _git(repository, "init", "-q")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "generated public native CSV qualification")
    pin = RepositoryPin(
        repository_symbol="fixture.csv.native.v4",
        commit=_git(repository, "rev-parse", "HEAD").decode().strip(),
        tree=_git(repository, "rev-parse", "HEAD^{tree}").decode().strip(),
        archive_sha256=hashlib.sha256(
            _git(repository, "archive", "--format=tar", "HEAD")
        ).hexdigest(),
    )
    for name in WRITE_PATHS:
        (repository / name).write_bytes(after[name])
    patch = _git(repository, "diff", "--no-ext-diff", "--no-textconv", "--", *WRITE_PATHS)
    for name in WRITE_PATHS:
        (repository / name).write_bytes(before[name])
    if _git(repository, "status", "--porcelain") or not patch:
        raise ValueError("CSV native generated baseline did not remain clean")
    csv = _csv_pins(before, after)
    (root / "source.patch").write_bytes(patch)
    return CsvNativeSource(repository, pin, patch, csv)


def _csv_pins(before: dict[str, bytes], after: dict[str, bytes]) -> CsvRegressionPins:
    module, test = "packages/shared/src/csv/index.ts", "packages/shared/src/csv/csv.test.ts"
    return CsvRegressionPins(
        baseline_module_sha256=hashlib.sha256(before[module]).hexdigest(),
        post_module_sha256=hashlib.sha256(after[module]).hexdigest(),
        baseline_test_sha256=hashlib.sha256(before[test]).hexdigest(),
        post_test_sha256=hashlib.sha256(after[test]).hexdigest(),
        mapping_sha256=mapping_sha256(),
        wrapper_sha256=csv_wrapper_sha256(),
        shared_test_files=tuple(
            sorted(
                name.removeprefix("packages/shared/")
                for name in before
                if name.startswith("packages/shared/") and name.endswith(".test.ts")
            )
        ),
        web_test_files=tuple(
            sorted(
                name.removeprefix("apps/web/")
                for name in before
                if name.startswith("apps/web/") and name.endswith(".test.ts")
            )
        ),
    )


def _git(repository: Path, *arguments: str) -> bytes:
    # Only NEW harmless fixture Git mutations, no hooks/global config/remote commands.
    return subprocess.check_output(
        (
            "/usr/bin/git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.autocrlf=false",
            "-C",
            str(repository),
            *arguments,
        ),
        timeout=15,
        stderr=subprocess.DEVNULL,
        env={
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_AUTHOR_NAME": "PublicFixture",
            "GIT_COMMITTER_NAME": "PublicFixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "GIT_AUTHOR_DATE": "2026-10-15T00:00:00Z",
            "GIT_COMMITTER_DATE": "2026-10-15T00:00:00Z",
        },
    )
