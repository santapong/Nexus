"""Verify the narrow Ruff exception for published legacy Alembic files.

Run alongside ``ruff check .``. Revision hashes come from main commit
6a8c8ef15e522aaa563d53776aef8dedc3209fcf; env.py diagnostics were recorded
from feature commit 1dcf415. The diagnostic fingerprint also covers the full
source spans, so a new finding of an already ignored rule does not disappear.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REVISION_HASHES = {
    "alembic/versions/001_initial_schema.py": (
        "3fd899a09e5a03eb6d0954c3f1fbd7da7a70b74b0c03e0596728b4ac3f14442c"
    ),
    "alembic/versions/002_dead_letters_and_a2a_tokens.py": (
        "48eebd3e5ee0adcfcd30559f2329b028d8062ff433099ee19e388b8697bbaec6"
    ),
    "alembic/versions/003_eval_results.py": (
        "02a551925556b6e4ed6e02f08b4aa29977179b38ddaca982cca446d96bef789a"
    ),
    "alembic/versions/004_phase4_multi_tenant.py": (
        "68da3231fca7b71a0eb861dee6da7caa9af625d7edaf9d5f7c2535297d96fde6"
    ),
    "alembic/versions/005_performance_indexes.py": (
        "486ff9a74acb34581291238710f47ef2484d00b817a30a313c073ea760666dbf"
    ),
    "alembic/versions/006_rls_policies.py": (
        "5938f54554bd4845b687b8f38d8faf38ac6aa17a959cb6ba0e76022dbf22fcb8"
    ),
    "alembic/versions/007_phase5_track_b_c.py": (
        "138d6cd4ccccc9244bf8f4c84085c1621eb5a1a6892d1019c061c16366cdf254"
    ),
    "alembic/versions/008_phase5_remaining.py": (
        "93acd1a2a45b4e5fa98d3af2840c7675792f7a6948fe513ca908fd03d846977d"
    ),
    "alembic/versions/009_security_and_federation.py": (
        "e5429aa02c74d26c0b1b59be240c2e7d7b87e2d0d8cc513e7d2a4318453dc587"
    ),
    "alembic/versions/010_conference_room_messaging.py": (
        "a8ac8c97738459c01172e8880c3ac6a3ff1a42ba6434f19a2294aa23519ef26c"
    ),
    "alembic/versions/011_workspace_storage.py": (
        "29ab409ee4421fbb63ac260798341dc922e568831b4fbd6c53eb07ea8221e9c0"
    ),
    "alembic/versions/012_audit_perf_indexes.py": (
        "f8430460046fa2d38dc3b09a68a3af7348ecc2346b5da4bb63deb855b12641cf"
    ),
    "alembic/versions/013_encrypt_oauth_tokens.py": (
        "c4abff1cae84a26e2d1c16ee80398dc03fbc4e0a3fdb6029c1d1d1865d6a0dd3"
    ),
    "alembic/versions/014_a2a_pbkdf2_hashing.py": (
        "32288d952ef273079220cbee788a1ea16cf234dfb422bf7cdc2b23f490f24f78"
    ),
    "alembic/versions/015_audit_log_partition_immutable.py": (
        "4c9ce626b7b122e9e49d7ccc77f7e2be0ed37601b84fc844fc4824564b77d919"
    ),
    "alembic/versions/016_attachments.py": (
        "21161a1d7bbdedbde3494eb6187546839ade364e9731dbe6c737cdffe9d13912"
    ),
}
BASELINE_FILES = {
    "alembic/env.py",
    *(
        path
        for path in REVISION_HASHES
        if Path(path).name[:3]
        in {"001", "002", "003", "004", "005", "007", "008", "009", "010", "011", "016"}
    ),
}
EXPECTED_DIAGNOSTIC_COUNT = 83
EXPECTED_DIAGNOSTIC_SHA256 = "670a14ff014c36531c5c5f6ff12e0ae5742609a956ef2c054215a4a555beb2bd"
MAX_SOURCE_BYTES = 1024 * 1024


def _source(backend: Path, name: str) -> bytes:
    root = backend.resolve(strict=True)
    candidate = root / name
    try:
        resolved = candidate.resolve(strict=True)
        if resolved != candidate or not resolved.is_file():
            raise ValueError(f"non-regular or redirected source: {name}")
        if resolved.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError(f"source exceeds size limit: {name}")
        return resolved.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read source: {name}") from exc


def check_migration_hashes(backend: Path, hashes: dict[str, str]) -> None:
    """Fail if a protected published revision is missing or changed."""
    for name, expected in hashes.items():
        if hashlib.sha256(_source(backend, name)).hexdigest() != expected:
            raise ValueError(f"published migration changed: {name}")


def parse_ruff_output(returncode: int, output: str) -> list[dict[str, Any]]:
    """Accept only a successful Ruff invocation with valid diagnostics JSON."""
    if returncode not in (0, 1):
        raise ValueError(f"Ruff failed to execute: exit {returncode}")
    try:
        decoded = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError("Ruff returned invalid JSON") from exc
    if not isinstance(decoded, list) or not all(isinstance(row, dict) for row in decoded):
        raise ValueError("Ruff returned invalid diagnostics")
    return decoded


def baseline_digest(backend: Path, diagnostics: list[dict[str, Any]], files: set[str]) -> str:
    """Fingerprint the diagnostic multiset and its entire source line spans."""
    root = backend.resolve(strict=True)
    entries: list[str] = []
    for row in diagnostics:
        try:
            path = Path(row["filename"])
            name = path.relative_to(root).as_posix()
            if name not in files or path.resolve(strict=True) != path:
                raise ValueError("unexpected or redirected diagnostic file")
            code, message = row["code"], row["message"]
            start, end = row["location"], row["end_location"]
            if not isinstance(code, str) or not isinstance(message, str):
                raise ValueError("invalid diagnostic text")
            positions = (start["row"], start["column"], end["row"], end["column"])
            if not all(type(value) is int and value > 0 for value in positions):
                raise ValueError("invalid diagnostic position")
            lines = _source(root, name).decode("utf-8").splitlines(keepends=True)
            first, _, last, _ = positions
            if first > last or last > len(lines):
                raise ValueError("diagnostic span outside source")
            span_sha = hashlib.sha256("".join(lines[first - 1 : last]).encode()).hexdigest()
            entries.append(json.dumps([name, code, message, *positions, span_sha]))
        except (KeyError, TypeError, UnicodeError, OSError) as exc:
            raise ValueError("invalid Ruff diagnostic") from exc
    payload = json.dumps(sorted(entries), separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    """Run pinned Ruff without the per-file exceptions and verify its baseline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ruff", default="ruff", help="path to locked Ruff executable")
    args = parser.parse_args()
    backend = Path(__file__).resolve().parent.parent
    try:
        check_migration_hashes(backend, REVISION_HASHES)
        version = subprocess.run(
            [args.ruff, "--version"], capture_output=True, text=True, check=False, timeout=20
        )
        if version.returncode != 0 or version.stdout.strip() != "ruff 0.15.21":
            raise ValueError("expected locked Ruff 0.15.21")
        result = subprocess.run(
            [
                args.ruff,
                "check",
                "--no-cache",
                "--ignore-noqa",
                "--output-format=json",
                "--config",
                "lint.per-file-ignores = {}",
                *sorted(BASELINE_FILES),
            ],
            cwd=backend,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        diagnostics = parse_ruff_output(result.returncode, result.stdout)
        digest = baseline_digest(backend, diagnostics, BASELINE_FILES)
        if len(diagnostics) != EXPECTED_DIAGNOSTIC_COUNT or digest != EXPECTED_DIAGNOSTIC_SHA256:
            raise ValueError(
                f"legacy diagnostics changed: {len(diagnostics)} findings, SHA256 {digest}"
            )
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"legacy Ruff baseline check failed: {exc}\n")
        return 1
    sys.stdout.write("Published legacy migration hashes and Ruff baseline verified.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
