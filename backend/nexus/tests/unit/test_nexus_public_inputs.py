"""Public lock/ABI checks do not download, install, or qualify native execution."""

import base64
import hashlib
import json
import os
import runpy
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from nexus.builder.nexus_public_inputs import (
    BUILD_PINS,
    NexusPublicInputs,
    PythonWheel,
    describe_public_inputs,
    offline_preparation_commands,
    validate_public_inputs,
    verify_public_blob,
)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def source_inputs() -> tuple[bytes, bytes, bytes, bytes]:
    project = b'[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
    lock = b"""version = 1
revision = 3
[[package]]
name = "nexus"
version = "0.1.0"
source = { editable = "." }
"""
    for wheel in selected_test_wheels():
        lock += (
            f'\n[[package]]\nname="{wheel.name}"\nversion="{wheel.version}"\nsource={{registry="https://pypi.org/simple"}}\n'
            f'wheels=[{{url="{wheel.url}",hash="sha256:{wheel.sha256}",size={wheel.byte_length}}}]\n'
        ).encode()
    package = {
        "name": "nexus-frontend",
        "version": "0.1.0",
        "scripts": {"build": "tsc && vite build"},
    }
    npm = {
        "name": "nexus-frontend",
        "version": "0.1.0",
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "nexus-frontend", "version": "0.1.0"},
            "node_modules/thing": {
                "version": "1.0.0",
                "resolved": "https://registry.npmjs.org/thing/-/thing-1.0.0.tgz",
                "integrity": "sha512-" + base64.b64encode(b"x" * 64).decode(),
            },
        },
    }
    return project, lock, json.dumps(package).encode(), json.dumps(npm).encode()


def build_wheels() -> tuple[PythonWheel, ...]:
    # Real public five-wheel hashes; synthetic URLs are public descriptor test data.
    return tuple(
        PythonWheel(
            name=name,
            version=version,
            filename=f"{name.replace('-', '_')}-{version}-py3-none-any.whl",
            url=(
                "https://files.pythonhosted.org/packages/test/"
                f"{name.replace('-', '_')}-{version}-py3-none-any.whl"
            ),
            sha256=sha,
            byte_length=size,
        )
        for name, version, sha, size in BUILD_PINS
    )


def selected_test_wheels() -> tuple[PythonWheel, ...]:
    """Synthetic public lock nominees; supplied tree/receipt tests never claim installation."""
    return tuple(
        PythonWheel(
            name=name,
            version="1.0",
            filename=f"{name.replace('-', '_')}-1.0-py3-none-any.whl",
            url=(
                "https://files.pythonhosted.org/packages/test/"
                f"{name.replace('-', '_')}-1.0-py3-none-any.whl"
            ),
            sha256="d" * 64,
            byte_length=32,
        )
        for name in ("anyio", "pydantic", "pytest", "pytest-asyncio")
    )


def public_case() -> NexusPublicInputs:
    return describe_public_inputs(
        *source_inputs(), platform="linux/amd64", build_wheels=build_wheels()
    )


def test_closed_real_hash_build_closure_and_offline_command_description() -> None:
    inputs = public_case()
    validate_public_inputs(inputs, *source_inputs())
    commands = offline_preparation_commands(inputs)
    assert "--require-hashes" in commands[0] and "--only-binary=:all:" in commands[0]
    assert commands[1][-2:] == ("ci", "--offline")
    assert "--ignore-scripts" in commands[1] and "--include=optional" in commands[1]
    lock = Path(__file__).parents[2] / "builder/assets/nexus-build-requirements.txt"
    assert digest(lock.read_bytes()) == inputs.build_requirements_sha256
    assert len(inputs.build_wheels) == 5 and inputs.test_wheels == ()


@pytest.mark.parametrize("index", range(4))
def test_each_original_source_lock_pin_is_required(index: int) -> None:
    values = list(source_inputs())
    values[index] += b" "
    with pytest.raises(ValueError, match="source"):
        validate_public_inputs(public_case(), *values)


@pytest.mark.parametrize(
    "change", ["private", "integrity", "link", "negative-platform", "root-hook", "crossed-root"]
)
def test_npm_public_resolution_and_platform_are_closed(change: str) -> None:
    project, uv, raw, lock = source_inputs()
    package, npm = json.loads(raw), json.loads(lock)
    item = npm["packages"]["node_modules/thing"]
    if change == "private":
        item["resolved"] = "https://user:secret@registry.npmjs.org/thing/-/thing-1.0.0.tgz"
    elif change == "integrity":
        item.pop("integrity")
    elif change == "link":
        item["link"] = True
    elif change == "negative-platform":
        item["cpu"] = ["!arm64"]
    elif change == "root-hook":
        package["scripts"]["prebuild"] = "curl https://example.invalid"
    else:
        npm["packages"][""]["dependencies"] = {"unlocked": "*"}
    with pytest.raises(ValueError):
        describe_public_inputs(
            project,
            uv,
            json.dumps(package).encode(),
            json.dumps(npm).encode(),
            platform="linux/amd64",
            build_wheels=build_wheels(),
        )


def test_platform_native_wheel_and_build_hash_substitution_deny() -> None:
    wheels = build_wheels()
    with pytest.raises(ValueError, match="build"):
        describe_public_inputs(*source_inputs(), platform="linux/amd64", build_wheels=wheels[:-1])
    changed = wheels[0].model_copy(update={"sha256": "0" * 64})
    with pytest.raises(ValueError, match="build"):
        describe_public_inputs(
            *source_inputs(), platform="linux/amd64", build_wheels=(changed, *wheels[1:])
        )
    wrong = PythonWheel(
        name="native",
        version="1.0",
        filename="native-1.0-cp312-cp312-manylinux_2_17_aarch64.whl",
        url="https://files.pythonhosted.org/packages/test/native-1.0-cp312-cp312-manylinux_2_17_aarch64.whl",
        sha256="a" * 64,
        byte_length=20,
    )
    project, uv, package, npm = source_inputs()
    uv += (
        f'\n[[package]]\nname="native"\nversion="1.0"\nsource={{registry="https://pypi.org/simple"}}\n'
        f'wheels=[{{url="{wrong.url}",hash="sha256:{wrong.sha256}",size=20}}]\n'
    ).encode()
    with pytest.raises(ValueError, match="platform"):
        describe_public_inputs(
            project,
            uv,
            package,
            npm,
            platform="linux/amd64",
            build_wheels=wheels,
            test_wheels=(wrong,),
        )


def test_uv_private_registry_and_duplicate_json_never_resolve() -> None:
    project, uv, package, npm = source_inputs()
    uv += (
        b'\n[[package]]\nname="private"\nversion="1"\nsource={registry="https://private.invalid"}\n'
    )
    with pytest.raises(ValueError, match="public"):
        describe_public_inputs(
            project, uv, package, npm, platform="linux/amd64", build_wheels=build_wheels()
        )
    with pytest.raises(ValueError, match="duplicate"):
        describe_public_inputs(
            project,
            source_inputs()[1],
            b'{"name":"a","name":"b"}',
            npm,
            platform="linux/amd64",
            build_wheels=build_wheels(),
        )


def test_actual_current_nexus_lock_metadata_has_public_platform_closure() -> None:
    root = Path(__file__).parents[4]
    inputs = describe_public_inputs(
        (root / "backend/pyproject.toml").read_bytes(),
        (root / "backend/uv.lock").read_bytes(),
        (root / "frontend/package.json").read_bytes(),
        (root / "frontend/package-lock.json").read_bytes(),
        platform="linux/amd64",
        build_wheels=build_wheels(),
    )
    assert inputs.test_wheels == ()  # No actual test-env/cold-image readiness is inferred.
    assert {"typescript", "vite", "@esbuild/linux-x64", "@rollup/rollup-linux-x64-gnu"} <= {
        row.name for row in inputs.npm_packages
    }
    assert not any("linux-arm64" in row.name for row in inputs.npm_packages)


def test_actual_public_blob_corruption_and_wrong_platform_do_not_pass_metadata_only() -> None:
    raw = b"bounded synthetic artifact bytes"
    wheel = PythonWheel(
        name="sample",
        version="1.0",
        filename="sample-1.0-py3-none-any.whl",
        url="https://files.pythonhosted.org/packages/test/sample-1.0-py3-none-any.whl",
        sha256=digest(raw),
        byte_length=len(raw),
    )
    verify_public_blob(wheel, raw)
    with pytest.raises(ValueError, match="hash/length"):
        verify_public_blob(wheel, raw + b"corrupt")
    package = (
        public_case()
        .npm_packages[0]
        .model_copy(
            update={
                "integrity": "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode()
            }
        )
    )
    verify_public_blob(package, raw)
    with pytest.raises(ValueError, match="integrity"):
        verify_public_blob(package, raw + b"corrupt")
    wheel.require_platform("linux/arm64")  # Universal wheel, not an amd64 relabeling.


def metadata_reader() -> Callable[[Path, int], bytes]:
    """Load the exact inert CLI function; no operator main or package process runs."""
    script = Path(__file__).parents[3] / "scripts/nexus_toolchain_inputs.py"
    return cast(
        Callable[[Path, int], bytes],
        runpy.run_path(str(script), run_name="nexus_metadata_read_unit")["bounded_read"],
    )


def test_first_ordinary_metadata_read_accepts_atime_advance(tmp_path: Path) -> None:
    path = tmp_path / "public-metadata.json"
    raw = b'{"scope":"synthetic first-read metadata"}'
    path.write_bytes(raw)
    mtime = time.time_ns()
    os.utime(path, ns=(mtime - 172_800_000_000_000, mtime))
    first = path.stat()  # Metadata only: do not pre-read bytes and warm access time.
    try:
        assert metadata_reader()(path, 1024) == raw
    finally:
        after = path.stat()
        (tmp_path / "first-read-observation.json").write_text(
            json.dumps(
                {
                    "before_atime_ns": first.st_atime_ns,
                    "after_atime_ns": after.st_atime_ns,
                    "atime_advanced": after.st_atime_ns > first.st_atime_ns,
                    "before_mtime_ns": first.st_mtime_ns,
                    "after_mtime_ns": after.st_mtime_ns,
                    "before_inode": first.st_ino,
                    "after_inode": after.st_ino,
                    "expected_sha256": digest(raw),
                    "actual_sha256": digest(path.read_bytes()),
                },
                sort_keys=True,
            )
        )
    assert after.st_ino == first.st_ino and after.st_mtime_ns == first.st_mtime_ns
    assert after.st_atime_ns >= first.st_atime_ns


@pytest.mark.parametrize(
    "failure", ["symlink", "hardlink", "oversize", "tamper", "replace", "mtime-ns"]
)
def test_metadata_read_preserves_actual_object_and_bound_denials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    path = tmp_path / "public-metadata.json"
    path.write_bytes(b"original public metadata")
    limit = 1024
    if failure == "symlink":
        link = tmp_path / "link.json"
        link.symlink_to(path)
        path = link
    elif failure == "hardlink":
        os.link(path, tmp_path / "second-name.json")
    elif failure == "oversize":
        limit = 3
    else:
        original_fstat = os.fstat
        calls = 0

        def change(fd: int) -> os.stat_result:
            nonlocal calls
            calls += 1
            value = original_fstat(fd)
            if calls == 2:
                if failure == "tamper":
                    path.write_bytes(b"modified public metadata")
                elif failure == "mtime-ns":
                    stamp = path.stat()
                    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1))
                else:
                    replacement = tmp_path / "new-inode.json"
                    replacement.write_bytes(b"original public metadata")
                    replacement.replace(path)
                value = original_fstat(fd)
            return value

        monkeypatch.setattr(os, "fstat", change)
    with pytest.raises(ValueError):
        metadata_reader()(path, limit)
