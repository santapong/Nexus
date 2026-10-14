"""Actual FD-anchored cleanup preserves originals/logs/outputs and rejects parent splices."""

import subprocess
import sys
from pathlib import Path

import pytest

from nexus.builder.node_phase_cleanup import cleanup_script


def invoke(tmp_path: Path) -> int:
    # Only a harmless test path replaces the fixed runtime /scratch literal.
    code = cleanup_script().replace('"/scratch"', repr(str(tmp_path / "scratch")))
    return subprocess.run(
        [sys.executable, "-c", code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
    ).returncode


def test_ordinary_phase_cleanup_unlinks_internal_symlinks_without_following(tmp_path: Path) -> None:
    baseline = tmp_path / "scratch/work/baseline"
    baseline.mkdir(parents=True)
    logs = tmp_path / "scratch/logs"
    logs.mkdir()
    (logs / "actual").write_text("baseline logs")
    output = tmp_path / "outputs/baseline"
    output.mkdir(parents=True)
    (output / "check").write_text("actual checks")
    source = tmp_path / "source/baseline"
    source.mkdir(parents=True)
    (source / "original").write_text("readonly source")
    source.chmod(0o500)
    (baseline / "files").mkdir()
    (baseline / "files/data").write_bytes(b"copied build bytes")
    (baseline / "external-link").symlink_to(output, target_is_directory=True)
    assert invoke(tmp_path) == 0 and not baseline.exists()
    assert (output / "check").read_text() == "actual checks"
    assert (logs / "actual").read_text() == "baseline logs"
    assert (source / "original").read_text() == "readonly source"


@pytest.mark.parametrize("target", ["work", "baseline"])
def test_parent_or_baseline_symlink_cannot_delete_neighbor_outputs(
    tmp_path: Path, target: str
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    output = tmp_path / "outside"
    (output / "baseline").mkdir(parents=True)
    (output / "baseline/retained").write_text("must remain")
    if target == "work":
        (scratch / "work").symlink_to(output, target_is_directory=True)
    else:
        (scratch / "work").mkdir()
        (scratch / "work/baseline").symlink_to(output / "baseline", target_is_directory=True)
    assert invoke(tmp_path) != 0
    assert (output / "baseline/retained").read_text() == "must remain"
