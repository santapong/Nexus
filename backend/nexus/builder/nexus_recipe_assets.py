"""Fixed image-resident Nexus recipe bytes; no asset is an execution or quality claim."""

# ruff: noqa: E501 -- immutable embedded script bytes retain their explicit reviewed layout.

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from nexus.builder.node_phase_cleanup import cleanup_script

BEHAVIOR_CASE_IDS = (
    "nexus.canonical.usd-six-places.v1",
    "nexus.canonical.unicode-fidelity.v1",
    "nexus.canonical.unordered-determinism.v1",
    "nexus.canonical.naive-time-denied.v1",
)
OFFLINE_NPMRC = "offline=true\nignore-scripts=true\naudit=false\nfund=false\nregistry=https://registry.npmjs.org/\n"
_BEHAVIOR = """def canonical_assertions(canonical):
    import hashlib
    from datetime import UTC, datetime
    from decimal import Decimal
    class Probe(canonical.BaseModel):
        amount_usd: Decimal
        label: str
        values: frozenset[str]
        when: datetime
    first = Probe(amount_usd=Decimal("1.23"), label="ไทย", values=frozenset({"a", "b"}), when=datetime(2026, 1, 1, tzinfo=UTC))
    def money():
        assert '"amount_usd":"1.230000"' in canonical.canonical_json(first)
    def unicode():
        assert "ไทย" in canonical.canonical_json(first)
    def unordered():
        second = first.model_copy(update={"values": frozenset(["b", "a"])})
        assert canonical.canonical_sha256(first) == canonical.canonical_sha256(second)
        assert canonical.canonical_sha256(first) == hashlib.sha256(canonical.canonical_json(first).encode()).hexdigest()
    def naive():
        try:
            canonical.canonical_json(first.model_copy(update={"when": datetime(2026, 1, 1)}))
        except ValueError:
            return
        raise AssertionError("Naive instant was accepted")
    cases = []
    for case_id, assertion in zip(CASE_IDS, (money, unicode, unordered, naive), strict=True):
        try:
            assertion()
            status = "pass"
        except (AssertionError, ValueError, TypeError):
            status = "fail"
        cases.append({"case_id": case_id, "status": status})
    return {"schema_version": "nexus.engineering.behavior.v1", "cases": cases}
"""


def canonical_assertions(canonical: ModuleType) -> dict[str, object]:
    """Execute the exact fixed image assertions against the supplied real canonical module."""
    namespace: dict[str, Any] = {
        "CASE_IDS": BEHAVIOR_CASE_IDS
    }  # Fixed compiled asset, no input code.
    exec(compile(_BEHAVIOR, "nexus-canonical-assertions", "exec"), namespace)
    value: dict[str, object] = namespace["canonical_assertions"](canonical)
    return value


def wrapper_source() -> str:
    """One finite image script shares the original generic outer command/job containment."""
    # Keep image script cohesive: source/dependency validation, fixed phases, real assertions,
    # bounded capture and the original descriptor-relative cleanup form one reviewed asset.
    header = "CASE_IDS = " + repr(BEHAVIOR_CASE_IDS) + "\n"
    header += "CLEANUP = " + repr(cleanup_script()) + "\n"
    header += "OFFLINE_NPMRC = " + repr(OFFLINE_NPMRC) + "\n"
    return _WRAPPER + header + _BEHAVIOR + _MAIN


def assets_sha256() -> str:
    """Hash exact source assets, including immutable build5 requirements and cleanup bytes."""
    folder = Path(__file__).parent / "assets"
    value = {
        "wrapper": wrapper_source(),
        "cleanup": cleanup_script(),
        "npmrc": OFFLINE_NPMRC,
        "Containerfile": (folder / "nexus-python-npm.Containerfile").read_text(),
        "build_requirements": (folder / "nexus-build-requirements.txt").read_text(),
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


_WRAPPER = """import argparse, hashlib, importlib.util, json, os, pathlib, stat, subprocess, sys, tempfile, time, zipfile
ROOT = pathlib.Path("/opt/nexus-recipe")
FLAGS = os.O_RDONLY | os.O_NOFOLLOW
END = time.monotonic() + 295
def signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
def current():
    if time.monotonic() >= END:
        raise TimeoutError("Original wrapper command end elapsed")
def read(path, limit):
    current()
    path = pathlib.Path(path)
    if path.resolve(strict=True) != path:
        raise ValueError("Changed ordinary recipe path")
    first = path.lstat()
    fd = os.open(path, FLAGS)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or not 0 <= opened.st_size <= limit:
            raise ValueError("Invalid bounded ordinary recipe input")
        original = signature(first)
        if signature(opened) != original:
            raise ValueError("Recipe input changed before read")
        raw = os.read(fd, limit + 1)
        if len(raw) != first.st_size or signature(os.fstat(fd)) != original or signature(path.lstat()) != original:
            raise ValueError("Recipe input changed during read")
        return raw
    finally:
        os.close(fd)
def sha(raw):
    return hashlib.sha256(raw).hexdigest()
def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate recipe metadata")
        value[key] = item
    return value
def save(path, value):
    current()
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    if len(raw) > 16384:
        raise ValueError("Recipe evidence exceeds bound")
    with pathlib.Path(path).open("xb") as stream:
        stream.write(raw)
def tree_digest(root):
    root = pathlib.Path(root)
    if root.resolve(strict=True) != root:
        raise ValueError("Immutable dependency root changed")
    rows = []; total = 0
    for parent, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            current()
            path = pathlib.Path(parent) / name
            info = path.lstat(); rel = path.relative_to(root).as_posix()
            if len(rows) >= 100000:
                raise ValueError("Immutable dependency entry bound exceeded")
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                if rel != ".vite-temp" and not path.resolve(strict=True).is_relative_to(root) and str(path.resolve(strict=True)) != "/usr/local/bin/python3.12":
                    raise ValueError("Immutable dependency link escapes its image tree")
                if rel == ".vite-temp" and target != "/scratch/nexus-vite-temp":
                    raise ValueError("Unexpected Vite temporary link")
                rows.append([rel, "link", target])
            elif stat.S_ISDIR(info.st_mode):
                rows.append([rel, "dir", stat.S_IMODE(info.st_mode)])
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
                if total > 536870912:
                    raise ValueError("Immutable dependency bytes exceed bound")
                rows.append([rel, "file", stat.S_IMODE(info.st_mode), info.st_size, sha(read(path, 134217728))])
            else:
                raise ValueError("Special dependency object")
    return sha(json.dumps(sorted(rows), separators=(",", ":")).encode())
def verify_image(manifest):
    if sys.version_info[:3] != (3, 12, 9):
        raise ValueError("Wrong fixed Python version")
    vite = pathlib.Path("/opt/nexus-node-modules/.vite-temp")
    if not vite.is_symlink() or os.readlink(vite) != "/scratch/nexus-vite-temp":
        raise ValueError("Unqualified immutable Vite scratch layout")
    for key, root in (("test_tree_sha256", "/opt/nexus-test-venv"), ("build_tree_sha256", "/opt/nexus-build-venv"), ("node_tree_sha256", "/opt/nexus-node-modules")):
        if not manifest.get(key) or tree_digest(root) != manifest[key]:
            raise ValueError("Unqualified immutable dependency tree")
    if not manifest.get("base_image") or not manifest.get("cold_offline_receipt_sha256") or not manifest.get("test_requirements_sha256"):
        raise ValueError("Unqualified image/base/cold offline preparation")
    if sha(read(ROOT / "test-requirements.txt", 2097152)) != manifest["test_requirements_sha256"]:
        raise ValueError("Immutable test dependency lock changed")
    assets = {"wrapper": read(ROOT / "check.py", 65536).decode(), "cleanup": CLEANUP, "npmrc": OFFLINE_NPMRC,
              "Containerfile": read(ROOT / "Containerfile", 16384).decode(), "build_requirements": read(ROOT / "nexus-build-requirements.txt", 16384).decode()}
    if sha(json.dumps(assets, sort_keys=True, separators=(",", ":")).encode()) != manifest["assets_sha256"]:
        raise ValueError("Image recipe assets changed")
    if read(ROOT / "offline.npmrc", 4096).decode() != OFFLINE_NPMRC or read(ROOT / "empty.npmrc", 4096) != b"# empty\\n":
        raise ValueError("Image npm configuration changed")
    run(["/opt/node/bin/node", "-e", "if(process.version !== 'v26.8.1' || require('/opt/node/lib/node_modules/npm/package.json').version !== '11.19.0') process.exit(1)"], ROOT, "image")
    with tempfile.TemporaryFile(dir="/tmp") as stream:
        result = subprocess.run(["/opt/uv/uv", "--version"], stdout=stream, env=environment("image"), timeout=max(0.001, END-time.monotonic()), check=False)
        stream.seek(0); version = stream.read(129)
        if result.returncode != 0 or len(version) > 128 or version.split()[:2] != [b"uv", b"0.12.5"]:
            raise ValueError("Wrong fixed uv version")
    current()
def environment(phase):
    return {"PATH": "/opt/node/bin:/usr/local/bin:/usr/bin:/bin", "CI": "1", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC", "HOME": "/tmp/home", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "UV_OFFLINE": "1", "UV_NO_CONFIG": "1", "UV_NO_CACHE": "1", "UV_PYTHON_DOWNLOADS": "never", "UV_CACHE_DIR": "/scratch/uv-" + phase, "XDG_CONFIG_HOME": "/scratch/config-" + phase, "XDG_CACHE_HOME": "/scratch/cache-" + phase}
def run(argv, cwd, phase):
    current()
    result = subprocess.run(argv, cwd=cwd, env=environment(phase), timeout=max(0.001, END-time.monotonic()), check=False)
    current()
    if result.returncode != 0:
        raise RuntimeError("Fixed Nexus command failed")
def source_files(root):
    rows = []; total = 0; entries = 0
    for parent, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            current(); entries += 1
            if entries > 4096:
                raise ValueError("Original source entry bound exceeded")
            path = pathlib.Path(parent) / name
            if path.is_symlink() or name in {".env", ".npmrc", ".pypirc", ".netrc", ".git", "node_modules", ".venv"}:
                raise ValueError("Unsupported source configuration/link")
            if path.is_file():
                raw = read(path, 16_777_216); total += len(raw)
                rows.append((path.relative_to(root).as_posix(), raw))
                if len(rows) > 4096 or total > 16_777_216:
                    raise ValueError("Original source archive bounds exceeded")
            elif not path.is_dir():
                raise ValueError("Special source object")
    return rows
def prepare_source(source, work, manifest):
    rows = source_files(source)
    pins = {r["path"]: r for r in manifest["source_files"]}
    for name, raw in rows:
        if name in pins and (sha(raw), len(raw)) != (pins[name]["sha256"], pins[name]["byte_length"]):
            raise ValueError("Frozen project lock/test/source changed")
    if not pins.keys() <= {name for name, raw in rows}:
        raise ValueError("Required frozen source is missing")
    if not work.exists():
        work.mkdir(mode=0o700, parents=True)
        for name, raw in rows:
            path = work / name; path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(raw)
        (work / "frontend/node_modules").symlink_to("/opt/nexus-node-modules", target_is_directory=True)
    modules = work / "frontend/node_modules"
    if not modules.is_symlink() or os.readlink(modules) != "/opt/nexus-node-modules":
        raise ValueError("Immutable phase node_modules link changed")
    for name, raw in rows:
        if read(work / name, 16_777_216) != raw:
            raise ValueError("Command altered its actual immutable phase source")
    for parent, dirs, files in os.walk(work, followlinks=False):
        if any(name in {".env", ".npmrc", ".pypirc", ".netrc"} for name in dirs + files):
            raise ValueError("Command introduced private configuration discovery")
    return rows
def export_dist(source, target):
    total = 0; count = 0
    target.mkdir(mode=0o700)
    for parent, dirs, files in os.walk(source, followlinks=False):
        for name in dirs + files:
            if (pathlib.Path(parent) / name).is_symlink():
                raise ValueError("Output link is not an artifact")
        for name in files:
            raw = read(pathlib.Path(parent) / name, 67108864); total += len(raw); count += 1
            if count > 256 or total > 67108864:
                raise ValueError("Original output envelope exceeded")
            path = target / (pathlib.Path(parent) / name).relative_to(source)
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(raw)
    if not count:
        raise ValueError("Actual build produced no artifacts")
"""

_MAIN = """def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("backend", "frontend-test", "frontend-build", "behavior", "image-check"))
    parser.add_argument("--behavior-child", action="store_true")
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    raw = read(ROOT / "manifest.json", 262144)
    if sha(raw) != args.manifest_sha256:
        raise ValueError("Frozen image manifest hash changed")
    manifest = json.loads(raw, object_pairs_hook=unique)
    verify_image(manifest)
    if args.command == "image-check":
        return
    source = pathlib.Path.cwd()
    if str(source) not in {"/source/baseline", "/source/post"}:
        raise ValueError("Nexus wrapper requires an exact readonly phase")
    phase = source.name; work = pathlib.Path("/scratch/work") / phase
    output = pathlib.Path("/outputs") / phase
    if os.environ.get("NEXUS_OUTPUT_DIR") != str(output):
        raise ValueError("Nexus phase/output differs")
    rows = prepare_source(source, work, manifest)
    checks = output / "checks"; checks.mkdir(mode=0o700, exist_ok=True)
    if args.command == "backend":
        run(["/opt/uv/uv", "build", "--python", "/opt/nexus-build-venv/bin/python", "--offline", "--no-build-isolation", "--wheel", "--out-dir", str(output / "backend-dist")], work / "backend", phase)
        wheels = list((output / "backend-dist").glob("*.whl"))
        if len(wheels) != 1:
            raise ValueError("Expected one actual backend wheel")
        with zipfile.ZipFile(wheels[0]) as archive:
            if archive.read("nexus/company/management/canonical.py") != read(work / "backend/nexus/company/management/canonical.py", 65536):
                raise ValueError("Built wheel does not contain actual phase canonical source")
        run(["/opt/nexus-test-venv/bin/python", "-m", "pytest", "-p", "pytest_asyncio.plugin", "-p", "anyio.pytest_plugin", "-p", "no:cacheprovider", "nexus/tests/unit/test_company_management_plans.py", "--basetemp=/scratch/pytest-" + phase, "-q"], work / "backend", phase)
    elif args.command == "frontend-test":
        for script in ("test-company-coding.mjs", "test-company-cycle-costs.mjs"):
            run(["/opt/node/bin/node", "scripts/" + script], work / "frontend", phase)
    elif args.command == "frontend-build":
        pathlib.Path("/scratch/nexus-vite-temp").mkdir(mode=0o700, exist_ok=True)
        run(["/opt/node/bin/node", "/opt/node/lib/node_modules/npm/bin/npm-cli.js", "--offline", "--ignore-scripts", "--userconfig=/opt/nexus-recipe/offline.npmrc", "--globalconfig=/opt/nexus-recipe/empty.npmrc", "--cache=/scratch/npm-" + phase, "run", "build"], work / "frontend", phase)
        export_dist(work / "frontend/dist", output / "frontend-dist")
    elif args.command == "behavior" and not args.behavior_child:
        run(["/opt/nexus-test-venv/bin/python", str(ROOT / "check.py"), "behavior", "--behavior-child", "--manifest-sha256", args.manifest_sha256], source, phase)
    else:
        path = work / "backend/nexus/company/management/canonical.py"
        spec = importlib.util.spec_from_file_location("nexus_fixed_canonical", path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        if pathlib.Path(module.__file__).resolve() != path:
            raise ValueError("Behavior imported another source")
        evidence = canonical_assertions(module)
        save(checks / "behavior.json", evidence)
        if any(row["status"] != "pass" for row in evidence["cases"]):
            raise AssertionError("Actual canonical assertion failed")
    prepare_source(source, work, manifest)
    if not args.behavior_child:
        save(checks / (args.command + ".json"), {"command_key": args.command, "manifest_sha256": args.manifest_sha256, "phase": phase, "exit_code": 0, "scope": "actual_mechanical_only"})
    if args.command == "behavior" and not args.behavior_child:
        exec(compile(CLEANUP.replace("baseline", phase), "original-phase-cleanup", "exec"), {})
    current()
if __name__ == "__main__":
    main()
"""
