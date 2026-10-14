"""Committed harmless phase source probes actual cleanup and retained outputs."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from nexus.builder.contracts import RepositoryPin
from nexus.tests.builder_node_support import repository


def phase_repository(root: Path, *, splice_baseline: bool = False) -> tuple[Path, RepositoryPin]:
    path, pin = repository(root, failed_baseline=False)
    package = json.loads((path / "package.json").read_text())
    package["scripts"]["build"] = "sh phase-check.sh"
    (path / "package.json").write_text(json.dumps(package))
    (path / "phase-check.sh").write_text(phase_script(splice_baseline=splice_baseline))

    def git(*args: str) -> bytes:
        return subprocess.check_output(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "commit.gpgsign=false",
                "-C",
                str(path),
                *args,
            ],
            stderr=subprocess.DEVNULL,
        )

    git("add", ".")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "harmless finite phase cleanup fixture",
    )
    return path, pin.model_copy(
        update={
            "commit": git("rev-parse", "HEAD").decode().strip(),
            "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
            "archive_sha256": hashlib.sha256(git("archive", "--format=tar", "HEAD")).hexdigest(),
        }
    )


def phase_script(*, splice_baseline: bool) -> str:
    baseline = (
        "cd /scratch/work; rm -rf -- baseline; ln -s /outputs/baseline baseline\n"
        if splice_baseline
        else "printf copied >baseline-private\n"
    )
    return (
        "set -eu\n"
        'if test "$NEXUS_OUTPUT_DIR" = /outputs/baseline; then\n'
        + baseline
        + "printf 'actual_baseline_phase_retained\\n'\n"
        "else\n"
        "test ! -e /scratch/work/baseline\n"
        "for key in install typecheck test build; do "
        'test -s "/outputs/baseline/checks/$key.json"; done\n'
        "for index in 0 1 2 3; do "
        'test -f "/scratch/logs/$index.out"; done\n'
        "test -f /source/baseline/phase-check.sh\n"
        "if touch /source/baseline/forbidden-write 2>/dev/null; then exit 28; fi\n"
        "printf 'actual_post_cleanup_baseline_outputs_logs_ro_source_retained\\n'\n"
        "fi\n"
    )
