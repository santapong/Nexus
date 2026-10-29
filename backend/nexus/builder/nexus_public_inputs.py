"""Closed Nexus public input descriptions; validation never acquires or executes packages."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import tomllib
from typing import Any, Literal, Self
from urllib.parse import unquote, urlsplit

from pydantic import Field, model_validator

from nexus.builder.contracts import BuilderValue, Digest
from nexus.builder.public_download import require_public_url
from nexus.builder.public_package_contracts import PublicPackage

NexusPlatform = Literal["linux/amd64", "linux/arm64"]
BUILD_REQUIREMENTS_SHA256 = "80691b474ce54202115be837c462e4f4ae8d47d8cdf27e00ae4930778caad342"
# Exact public ZIP metadata observed 2026-10-16, receipt80cd7c34; not image qualification.
BUILD_PINS = (
    (
        "hatchling",
        "1.27.0",
        "d3a2f3567c4f926ea39849cdf924c7e99e6686c9c8e288ae1037c8fa2a5d937b",
        75794,
    ),
    (
        "packaging",
        "25.0",
        "29572ef2b1f17581046b3a2227d5c611fb25ec70ca1ba8554b24b0e69331a484",
        66469,
    ),
    (
        "pathspec",
        "1.1.1",
        "a00ce642f577bf7f473932318056212bc4f8bfdf53128c78bbd5af0b9b20b189",
        57328,
    ),
    ("pluggy", "1.6.0", "e920276dd6813095e9377c0bc5566d94c932c33b27a3e3945d8389c374dd4746", 20538),
    (
        "trove-classifiers",
        "2025.9.11.17",
        "5d392f2d244deb1866556457d6f3516792124a23d1c3a463a2e8668a5d1c15dd",
        14158,
    ),
)


def sha256(raw: bytes) -> str:
    """Ordinary byte identity, distinct from management canonical payload hashing."""
    return hashlib.sha256(raw).hexdigest()


class PythonWheel(BuilderValue):
    """One selected exact public wheel; no sdist or guessed package-manager resolution."""

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,99}$")
    version: str = Field(pattern=r"^[0-9][A-Za-z0-9.!+_-]{0,99}$")
    filename: str = Field(pattern=r"^[A-Za-z0-9_.+-]{1,240}\.whl$")
    url: str = Field(max_length=1024)
    sha256: Digest
    byte_length: int = Field(gt=0, le=134_217_728, strict=True)

    @model_validator(mode="after")
    def exact_public_wheel(self) -> Self:
        require_public_url(self.url, frozenset({"files.pythonhosted.org"}))
        url = urlsplit(self.url)
        if (
            url.query
            or url.fragment
            or unquote(url.path.rsplit("/", 1)[-1]) != self.filename
            or not self.filename.startswith(self.name.replace("-", "_") + "-" + self.version + "-")
        ):
            raise ValueError("Python wheel public name/version/filename differs")
        return self

    def require_platform(self, platform: NexusPlatform) -> None:
        """Closed CPython3.12 glibc tags; unsupported wheels require a new qualification."""
        tags = self.filename.removesuffix(".whl").rsplit("-", 3)[-3:]
        if len(tags) != 3:
            raise ValueError("Python wheel platform tag is unavailable")
        python, abi, platforms = tags
        machine = "x86_64" if platform == "linux/amd64" else "aarch64"
        universal = python in {"py3", "py2.py3", "cp312"} and abi == "none" and platforms == "any"
        native = (
            (python == "cp312" and abi == "cp312")
            or (python in {"cp38", "cp39", "cp310", "cp311", "cp312"} and abi == "abi3")
        ) and all(
            re.fullmatch(r"manylinux(?:_2_(?:17|28)|2014)_" + machine, value)
            for value in platforms.split(".")
        )
        if not (universal or native):
            raise ValueError(
                "Python wheel platform/ABI is not the selected CPython312 glibc target"
            )


class NexusPublicInputs(BuilderValue):
    """Frozen source plus selected public bytes; host preparation is never native readiness."""

    schema_version: Literal["nexus.builder.public-inputs.v1"] = "nexus.builder.public-inputs.v1"
    platform: NexusPlatform
    pyproject_sha256: Digest
    uv_lock_sha256: Digest
    package_sha256: Digest
    npm_lock_sha256: Digest
    build_requirements_sha256: Digest = BUILD_REQUIREMENTS_SHA256
    build_wheels: tuple[PythonWheel, ...] = Field(min_length=5, max_length=5)
    test_wheels: tuple[PythonWheel, ...] = Field(default=(), max_length=1024)
    npm_packages: tuple[PublicPackage, ...] = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def exact_build_and_platform(self) -> Self:
        rows = tuple((r.name, r.version, r.sha256, r.byte_length) for r in self.build_wheels)
        if rows != BUILD_PINS or self.build_requirements_sha256 != BUILD_REQUIREMENTS_SHA256:
            raise ValueError("Nexus build closure differs from the five hash-locked public wheels")
        for wheels in (self.build_wheels, self.test_wheels):
            keys = tuple((r.name, r.version) for r in wheels)
            if keys != tuple(sorted(set(keys))):
                raise ValueError("Python selected wheel names must be unique and ordered")
            for wheel in wheels:
                wheel.require_platform(self.platform)
        keys = tuple((r.name, r.version) for r in self.npm_packages)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("Npm selected public package set must be unique and ordered")
        if sum(r.byte_length for r in (*self.build_wheels, *self.test_wheels)) > 536_870_912:
            raise ValueError("Python public wheel closure exceeds its fixed byte bound")
        return self


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Nexus package JSON has a duplicate key")
        result[key] = value
    return result


def _object(value: object) -> dict[str, Any]:
    # TOML/JSON produce untyped values; every used boundary is checked below before modeling.
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Nexus lock object is unavailable")
    return value


def _json(raw: bytes, limit: int) -> dict[str, Any]:
    if not 0 < len(raw) <= limit:
        raise ValueError("Nexus source metadata exceeds its fixed bound")
    return _object(json.loads(raw, object_pairs_hook=_unique))


def _uv(project: bytes, raw: bytes, wheels: tuple[PythonWheel, ...]) -> None:
    if not 0 < len(project) <= 65536 or not 0 < len(raw) <= 2_097_152:
        raise ValueError("Nexus source Python declaration exceeds its fixed bound")
    build = _object(tomllib.loads(project.decode()).get("build-system"))
    if build != {"requires": ["hatchling"], "build-backend": "hatchling.build"}:
        raise ValueError("Nexus source build backend requires separate locked qualification")
    lock = tomllib.loads(raw.decode())
    rows = lock.get("package")
    if (
        type(lock.get("version")) is not int
        or type(lock.get("revision")) is not int
        or lock.get("version") != 1
        or lock.get("revision") != 3
        or not isinstance(rows, list)
        or not 1 <= len(rows) <= 1024
    ):
        raise ValueError("Nexus uv lock version/package bounds are unsupported")
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    local = 0
    for row in rows:
        item = _object(row)
        source = item.get("source")
        if source == {"editable": "."} and item.get("name") == "nexus":
            local += 1
        elif source != {"registry": "https://pypi.org/simple"}:
            raise ValueError("Nexus uv lock requires only exact public registry dependencies")
        name, version = item.get("name"), item.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise ValueError("Nexus uv lock package identity is ambiguous")
        key = name, version
        if key in entries:
            raise ValueError("Nexus uv lock package identity is ambiguous")
        entries[key] = item
    if local != 1:
        raise ValueError("Nexus uv lock needs its sole local project")
    for wheel in wheels:
        candidates = entries.get((wheel.name, wheel.version), {}).get("wheels", [])
        if not any(
            isinstance(row, dict)
            and (row.get("url"), row.get("hash"), row.get("size"))
            == (wheel.url, "sha256:" + wheel.sha256, wheel.byte_length)
            for row in candidates
        ):
            raise ValueError("Selected test wheel differs from the actual uv source lock")


def _npm(package_raw: bytes, lock_raw: bytes, platform: NexusPlatform) -> tuple[PublicPackage, ...]:
    package, lock = _json(package_raw, 65536), _json(lock_raw, 2_097_152)
    packages = _object(lock.get("packages"))
    if (
        type(lock.get("lockfileVersion")) is not int
        or lock.get("lockfileVersion") != 3
        or not 2 <= len(packages) <= 1024
    ):
        raise ValueError("Nexus npm lock version/package bounds are unsupported")
    root = _object(packages.get(""))
    for key in ("name", "version", "dependencies", "devDependencies", "optionalDependencies"):
        if root.get(key, {}) != package.get(key, {}):
            raise ValueError("Nexus package declaration differs from the npm root lock")
    scripts = _object(package.get("scripts"))
    if scripts.get("build") != "tsc && vite build" or any(
        key in scripts
        for key in ("prebuild", "postbuild", "preinstall", "install", "postinstall", "prepare")
    ):
        raise ValueError("Nexus npm source scripts differ from the fixed build method")
    selected: dict[tuple[str, str], PublicPackage] = {}
    cpu = "x64" if platform == "linux/amd64" else "arm64"
    for path, row in packages.items():
        if not path:
            continue
        if not path.startswith("node_modules/") or ".." in path.split("/"):
            raise ValueError("Nexus npm dependency path is not an ordinary locked package")
        item = _object(row)
        if item.get("link"):
            raise ValueError("Nexus npm package requires unsupported links")
        name = path.rsplit("node_modules/", 1)[1]
        public = PublicPackage(
            name=name,
            version=item.get("version"),
            integrity=item.get("integrity"),
            url=item.get("resolved"),
        )
        keep = True
        for key, current in (("os", "linux"), ("cpu", cpu), ("libc", "glibc")):
            values = item.get(key, [])
            if not isinstance(values, list) or any(
                not isinstance(v, str) or v.startswith("!") for v in values
            ):
                raise ValueError("Nexus npm platform constraint is unsupported")
            if values and current not in values:
                if not item.get("optional"):
                    raise ValueError("Required Nexus npm dependency has another platform")
                keep = False
        if keep:
            # esbuild's declared hook is suppressed; its native package bytes are hash-pinned.
            if item.get("hasInstallScript") and path != "node_modules/esbuild":
                raise ValueError("Nexus npm package requires unsupported install scripts")
            package_key = public.name, public.version
            if package_key in selected and selected[package_key] != public:
                raise ValueError("Nexus npm repeated package has crossed integrity")
            selected[package_key] = public
    return tuple(selected[key] for key in sorted(selected))


def describe_public_inputs(
    pyproject: bytes,
    uv_lock: bytes,
    package: bytes,
    npm_lock: bytes,
    *,
    platform: NexusPlatform,
    build_wheels: tuple[PythonWheel, ...],
    test_wheels: tuple[PythonWheel, ...] = (),
) -> NexusPublicInputs:
    """Validate nominated source bytes without resolving, importing, or fetching packages."""
    _uv(pyproject, uv_lock, test_wheels)
    return NexusPublicInputs(
        platform=platform,
        pyproject_sha256=sha256(pyproject),
        uv_lock_sha256=sha256(uv_lock),
        package_sha256=sha256(package),
        npm_lock_sha256=sha256(npm_lock),
        build_wheels=build_wheels,
        test_wheels=test_wheels,
        npm_packages=_npm(package, npm_lock, platform),
    )


def validate_public_inputs(
    inputs: NexusPublicInputs, pyproject: bytes, uv_lock: bytes, package: bytes, npm_lock: bytes
) -> None:
    """Revalidate actual source bytes; copied-model updates cannot bypass field/closure checks."""
    expected = (
        inputs.pyproject_sha256,
        inputs.uv_lock_sha256,
        inputs.package_sha256,
        inputs.npm_lock_sha256,
    )
    if tuple(map(sha256, (pyproject, uv_lock, package, npm_lock))) != expected:
        raise ValueError("Nexus source lock bytes differ from their frozen input pins")
    actual = describe_public_inputs(
        pyproject,
        uv_lock,
        package,
        npm_lock,
        platform=inputs.platform,
        build_wheels=inputs.build_wheels,
        test_wheels=inputs.test_wheels,
    )
    if actual != inputs:
        raise ValueError("Nexus public input declaration differs from actual source resolution")


def offline_preparation_commands(inputs: NexusPublicInputs) -> tuple[tuple[str, ...], ...]:
    """Finite future preparation descriptions only; this function executes no command."""
    NexusPublicInputs.model_validate(inputs.model_dump())
    return (
        (
            "/opt/uv/uv",
            "pip",
            "install",
            "--python",
            "/opt/nexus-build-venv/bin/python",
            "--offline",
            "--no-index",
            "--find-links=/inputs/build-wheels",
            "--require-hashes",
            "--only-binary=:all:",
            "-r",
            "/inputs/nexus-build-requirements.txt",
        ),
        (
            "/opt/node/bin/node",
            "/opt/node/lib/node_modules/npm/bin/npm-cli.js",
            "--ignore-scripts",
            "--include=dev",
            "--include=optional",
            "--no-audit",
            "--no-fund",
            "--userconfig=/inputs/offline.npmrc",
            "--globalconfig=/inputs/empty.npmrc",
            "--cache=/inputs/npm-cache",
            "ci",
            "--offline",
        ),
    )


def verify_public_blob(value: PythonWheel | PublicPackage, raw: bytes) -> None:
    """Bounded integrity check before existing safe extraction; no metadata/code import claim."""
    if type(raw) is not bytes or not raw:
        raise ValueError("Public artifact requires actual nonempty bounded bytes")
    if isinstance(value, PythonWheel):
        value = PythonWheel.model_validate(value.model_dump())
        if len(raw) != value.byte_length or sha256(raw) != value.sha256:
            raise ValueError("Public wheel actual hash/length differs")
    else:
        value = PublicPackage.model_validate(value.model_dump())
        if (
            len(raw) > 33_554_432
            or "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode()
            != value.integrity
        ):
            raise ValueError("Public npm tarball actual integrity/byte bound differs")
