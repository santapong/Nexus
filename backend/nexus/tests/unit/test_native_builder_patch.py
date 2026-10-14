"""Actual Git-generated ordinary source changes preserve baseline and deny unsafe paths."""

import hashlib
import subprocess
from pathlib import Path

import pytest

from nexus.builder.patch_inventory import inventory, verify_snapshots
from nexus.builder.protected_patch import apply_patch, parse_patch


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(
        [
            "/usr/bin/git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "-C",
            str(root),
            *args,
        ],
        stderr=subprocess.DEVNULL,
        env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
    )


def sources(root: Path) -> tuple[Path, Path, bytes]:
    repo = root / "repo"
    repo.mkdir(mode=0o700)
    git(repo, "init", "-q")
    original = {"edit.py": b"old\ncontext\n", "delete.py": b"remove me\n"}
    for name, raw in original.items():
        (repo / name).write_bytes(raw)
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    baseline = root / "baseline"
    post = root / "post"
    for path in (baseline, post):
        path.mkdir(mode=0o700)
        for name, raw in original.items():
            (path / name).write_bytes(raw)
    (repo / "edit.py").write_text("new\ncontext\n")
    (repo / "delete.py").unlink()
    (repo / "tests").mkdir()
    (repo / "tests" / "test_new.py").write_text("def test_new():\n    assert True\n")
    git(repo, "add", ".")
    return baseline, post, git(repo, "diff", "--cached", "--no-ext-diff", "--no-textconv")


def test_actual_git_modify_create_delete_preserves_baseline(tmp_path: Path) -> None:
    baseline, post, raw = sources(tmp_path)
    before = inventory(baseline)
    patches = parse_patch(raw, hashlib.sha256(raw).hexdigest(), ("edit.py", "delete.py", "tests"))
    assert {row.operation for row in patches} == {"modify", "create", "delete"}
    apply_patch(post, patches)
    hashes = verify_snapshots(baseline, post, before, ("edit.py", "delete.py", "tests"))
    assert hashes[0] != hashes[1] and inventory(baseline) == before
    assert (post / "edit.py").read_bytes() == b"new\ncontext\n" and not (
        post / "delete.py"
    ).exists()
    assert (post / "tests" / "test_new.py").read_text() == "def test_new():\n    assert True\n"


@pytest.mark.parametrize("case", ["path", "hash", "context", "existing_create"])
def test_patch_denials_never_modify_baseline(tmp_path: Path, case: str) -> None:
    baseline, post, raw = sources(tmp_path)
    before = inventory(baseline)
    if case == "context":
        (post / "edit.py").write_text("different\ncontext\n")
    if case == "existing_create":
        (post / "tests").mkdir()
        (post / "tests" / "test_new.py").write_text("already exists")
    expected = "0" * 64 if case == "hash" else hashlib.sha256(raw).hexdigest()
    with pytest.raises((ValueError, FileExistsError)):
        patches = parse_patch(
            raw, expected, ("edit.py",) if case == "path" else ("edit.py", "delete.py", "tests")
        )
        apply_patch(post, patches)
    assert inventory(baseline) == before


def test_create_cannot_follow_symlink_parent_or_change_undeclared_file(tmp_path: Path) -> None:
    baseline, post, raw = sources(tmp_path)
    before = inventory(baseline)
    outside = tmp_path / "outside"
    outside.mkdir()
    (post / "tests").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        apply_patch(
            post,
            parse_patch(raw, hashlib.sha256(raw).hexdigest(), ("edit.py", "delete.py", "tests")),
        )
    assert tuple(outside.iterdir()) == () and inventory(baseline) == before
    (post / "tests").unlink()
    (post / "undeclared").write_text("secret change")
    with pytest.raises(ValueError, match="outside declared"):
        verify_snapshots(baseline, post, before, ("edit.py", "delete.py", "tests"))


@pytest.mark.parametrize("path", ["../outside", ".env", ".git/config", ".ssh/key"])
def test_forbidden_patch_path_denied_before_file_write(path: str) -> None:
    raw = (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
        f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1 @@\n+private\n"
    ).encode()
    with pytest.raises(ValueError):
        parse_patch(raw, hashlib.sha256(raw).hexdigest(), (path,))
