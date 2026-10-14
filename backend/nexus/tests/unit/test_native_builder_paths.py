"""Real local symlinks, FIFOs, hardlinks and size limits are denied before artifact reads."""

import hashlib
import os
from pathlib import Path

import pytest

from nexus.builder.paths import bounded_digest, permitted_path, relative_path


@pytest.mark.parametrize(
    "path",
    ["../secret", "/etc/passwd", "a/../secret", "a\\secret", ".git/config", "a//b", "a/", "a\x00b"],
)
def test_unsafe_paths_reject(path: str) -> None:
    with pytest.raises(ValueError):
        relative_path(path)


def test_artifact_fds_reject_symlink_parent_file_fifo_and_hardlink(tmp_path: Path) -> None:
    root = tmp_path / "job"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"private-outside")
    (root / "link").symlink_to(outside)
    (root / "parent").symlink_to(tmp_path, target_is_directory=True)
    os.mkfifo(root / "fifo")
    os.link(outside, root / "hardlink")
    for path in ("link", "parent/outside", "fifo", "hardlink"):
        with pytest.raises((ValueError, OSError)):
            bounded_digest(root, path, 64)


def test_exact_prefix_and_total_file_bound(tmp_path: Path) -> None:
    assert permitted_path("apps/web/src/answer.ts", ("apps/web/src",))
    assert not permitted_path("apps/web/src-other/answer.ts", ("apps/web/src",))
    (tmp_path / "result").write_bytes(b"actual-native-result")
    expected = hashlib.sha256(b"actual-native-result").hexdigest()
    assert bounded_digest(tmp_path, "result", 20) == (expected, 20)
    with pytest.raises(ValueError):
        bounded_digest(tmp_path, "result", 19)
