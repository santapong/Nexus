"""Server-owned finite offline Node commands record real exits and never infer readiness."""

from __future__ import annotations

import hashlib
import json
import shlex

from nexus.builder.contracts import CommandRef
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.node_phase_cleanup import cleanup_script
from nexus.builder.policy import BuilderCommandPolicy, BuilderToolPolicy
from nexus.builder.runtime_plan import runtime_script

COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "install",
        (
            "install",
            "--offline",
            "--ignore-scripts",
            "--ignore-pnpmfile",
            "--frozen-lockfile",
            "--store-dir",
            "/cache/store",
            "--package-import-method=copy",
        ),
    ),
    ("typecheck", ("--filter", "@stockflow/web", "typecheck")),
    ("test", ("--filter", "@stockflow/web", "test")),
    ("build", ("--filter", "@stockflow/web", "build")),
)
LEGACY_RECIPE_SHA256 = "93a7fa136d4fed501a7c8887663220bc578653e5dca660029e81282bdab0e1b7"
V2_RECIPE_SHA256 = "cc147490c889dc0fdf4e188e9b8a1f3e6478c9f6c62e865647ba2ad5f52e39ec"


def command_policies() -> tuple[BuilderCommandPolicy, ...]:
    return tuple(
        BuilderCommandPolicy(
            command_key=key, argv=("/bin/sh", f"/node-commands/{key}.sh"), directory="."
        )
        for key, _ in COMMANDS
    )


def command_references() -> tuple[CommandRef, ...]:
    return tuple(
        CommandRef(command_key=key, phase=phase)
        for phase in ("baseline", "post")
        for key, _ in COMMANDS
    )


def wrappers() -> dict[str, str]:
    result = {}
    for key, args in COMMANDS:
        command = ("/usr/local/bin/node", "/tools/package/bin/pnpm.cjs", *args)
        result[key] = (
            "\n".join(
                (
                    "#!/bin/sh",
                    "set +e",
                    shlex.join(command),
                    "code=$?",
                    "set -e",
                    'mkdir -p "$NEXUS_OUTPUT_DIR/checks"',
                    f'printf \'{{"command_key":"{key}","exit_code":%s,'
                    f'"scope":"local_mechanical_only"}}\\n\' "$code" '
                    f'>"$NEXUS_OUTPUT_DIR/checks/{key}.json"',
                    'exit "$code"',
                )
            )
            + "\n"
        )
    return result


def recipe_sha256() -> str:
    value = {
        "wrappers": wrappers(),
        "workspace": "readonly baseline/post copied into bounded scratch",
        "scratch_mount": "rw,nodev,nosuid,exec; hard workspace envelope unchanged",
        "loopback_hosts": loopback_hosts(),
        "offline_npmrc": config_text(),
        "startup": startup(),
        "baseline_cleanup_script": cleanup_script(),
        "phase_transition": phase_transition(),
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def config_text() -> str:
    return (
        "offline=true\nignore-scripts=true\nverify-store-integrity=true\nside-effects-cache=false\n"
        "ignore-pnpmfile=true\nenable-pre-post-scripts=false\n"
        "registry=https://registry.npmjs.org/\ncache-dir=/tmp/cache\nstate-dir=/tmp/state\n"
    )


def loopback_hosts() -> str:
    return "127.0.0.1 localhost\n::1 localhost\n"


def startup() -> str:
    return (
        "mkdir -p /scratch/work\ncp -R /source/baseline /scratch/work/baseline\n"
        "cp -R /source/post /scratch/work/post\n"
    )


def require_node_recipe(
    spec: BuilderExecutionSpec, policy: BuilderToolPolicy, *, execution: bool
) -> None:
    pins = spec.runtime_inputs
    if pins is None:
        raise ValueError("Native Node command recipe differs from approved pins")
    expected = {
        "nexus.builder.node.v1": LEGACY_RECIPE_SHA256,
        "nexus.builder.node.v2": V2_RECIPE_SHA256,
        "nexus.builder.node.v3": recipe_sha256(),
    }[pins.recipe]
    if pins.command_recipe_sha256 != expected:
        raise ValueError("Native Node command recipe differs from approved pins")
    if execution and pins.recipe != "nexus.builder.node.v3":
        raise ValueError("Legacy Node recipe permits known-result recovery only")
    if policy.commands != command_policies():
        raise ValueError("Native Node commands differ from exact server recipe")
    if spec.job.commands != command_references():
        raise ValueError("Native Node needs the complete ordered baseline/post recipe")


def node_script(spec: BuilderExecutionSpec, policy: BuilderToolPolicy) -> str:
    require_node_recipe(spec, policy, execution=True)
    original = (
        runtime_script(spec, policy)
        .replace("/source/baseline", "/scratch/work/baseline")
        .replace("/source/post", "/scratch/work/post")
    )
    script = original.replace(
        "mkdir -p /scratch/logs /outputs /tmp/home\n",
        "mkdir -p /scratch/logs /outputs /tmp/home\n" + startup(),
    )
    return script.replace(
        "cd /scratch/work/post\n", phase_transition() + "cd /scratch/work/post\n", 1
    )


def phase_transition() -> str:
    return (
        "if ! timeout --signal=KILL 30s /usr/bin/python3 /node-commands/phase-cleanup.py; "
        "then printf 'R phase_cleanup_failed\\nEND\\n'; exit 0; fi\n"
    )
