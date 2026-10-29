"""The legacy Ruff exception cannot conceal changed source or new findings."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_legacy_ruff_baseline import (
    BASELINE_FILES,
    REVISION_HASHES,
    baseline_digest,
    check_migration_hashes,
    parse_ruff_output,
)


def _diagnostic(path: Path, line: int, end_line: int) -> dict[str, object]:
    return {
        "filename": str(path),
        "code": "I001",
        "message": "Import block is un-sorted or un-formatted",
        "location": {"row": line, "column": 1},
        "end_location": {"row": end_line, "column": 2},
    }


def test_baseline_includes_every_line_in_diagnostic_span(tmp_path: Path) -> None:
    source = tmp_path / "env.py"
    source.write_text("import z\nimport a\n", encoding="utf-8")
    rows = [_diagnostic(source, 1, 2)]
    before = baseline_digest(tmp_path, rows, {"env.py"})
    source.write_text("import z\nimport b\n", encoding="utf-8")
    assert baseline_digest(tmp_path, rows, {"env.py"}) != before


def test_baseline_detects_new_or_duplicate_findings(tmp_path: Path) -> None:
    source = tmp_path / "env.py"
    source.write_text("import z\nimport a\n", encoding="utf-8")
    row = _diagnostic(source, 1, 2)
    before = baseline_digest(tmp_path, [row], {"env.py"})
    assert baseline_digest(tmp_path, [row, row], {"env.py"}) != before
    assert baseline_digest(tmp_path, [row, _diagnostic(source, 2, 2)], {"env.py"}) != before


def test_baseline_rejects_unexpected_source(tmp_path: Path) -> None:
    source = tmp_path / "other.py"
    source.write_text("import z\n", encoding="utf-8")
    with pytest.raises(ValueError):
        baseline_digest(tmp_path, [_diagnostic(source, 1, 1)], {"env.py"})


def test_migration_guard_detects_missing_and_changed_files(tmp_path: Path) -> None:
    expected = {"migration.py": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}
    migration = tmp_path / "migration.py"
    migration.write_bytes(b"abc")
    check_migration_hashes(tmp_path, expected)
    migration.write_bytes(b"abd")
    with pytest.raises(ValueError):
        check_migration_hashes(tmp_path, expected)
    migration.unlink()
    with pytest.raises(ValueError):
        check_migration_hashes(tmp_path, expected)


def test_ruff_guard_rejects_execution_and_json_errors() -> None:
    assert parse_ruff_output(1, "[]") == []
    with pytest.raises(ValueError):
        parse_ruff_output(2, "[]")
    with pytest.raises(ValueError):
        parse_ruff_output(1, "not json")
    with pytest.raises(ValueError):
        parse_ruff_output(1, "{}")


def test_real_ruff_guard_rejects_new_ignored_diagnostic(tmp_path: Path) -> None:
    source_root = Path(__file__).resolve().parents[3]
    script_name = "scripts/check_legacy_ruff_baseline.py"
    for name in {*BASELINE_FILES, *REVISION_HASHES, "pyproject.toml", script_name}:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_root / name, target)
    ruff = Path(sys.executable).with_name("ruff")
    command = [sys.executable, str(tmp_path / script_name), "--ruff", str(ruff)]
    original = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    assert original.returncode == 0, original.stderr
    env = tmp_path / "alembic/env.py"
    contents = env.read_text(encoding="utf-8")
    env.write_text(
        contents.replace("import asyncio\n", "import asyncio\nimport unexpected\n"),
        encoding="utf-8",
    )
    ordinary_ruff = subprocess.run(
        [str(ruff), "check", "--no-cache", "alembic/env.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert ordinary_ruff.returncode == 0, ordinary_ruff.stderr
    changed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    assert changed.returncode == 1
    assert "legacy diagnostics changed" in changed.stderr
    env.write_text(
        contents.replace("import asyncio\n", "import asyncio\nimport unexpected  # noqa: F401\n"),
        encoding="utf-8",
    )
    hidden = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    assert hidden.returncode == 1
    assert "legacy diagnostics changed" in hidden.stderr
