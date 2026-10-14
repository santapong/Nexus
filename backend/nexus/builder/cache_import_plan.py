"""One public offline cache import has hard store bounds and no project/customer inputs."""

from __future__ import annotations

from pathlib import Path

from nexus.builder.public_package_contracts import PublicPackageManifest

IMAGE = (
    "localhost/nexus-node-22.23.3-bookworm@"
    "sha256:c4d5523090a817b7aa86d2111241fdd4f66d1e27782b44160e6aa63b357ecb2d"
)
NAME = "nexus-builder-stockflow-cache-20261014-v1"


def import_script(manifest: PublicPackageManifest) -> str:
    paths = ["/downloads/" + row.filename for row in manifest.packages]
    rows = [
        "#!/bin/sh",
        "set -eu",
        "mkdir -p /tmp/home /cache/store /scratch/work",
        "cd /scratch/work",
        "printf 'NODE ' >&2; node --version >&2",
        "printf 'PNPM ' >&2; node /tools/package/bin/pnpm.cjs --version >&2",
    ]
    for index in range(0, len(paths), 32):
        command = "node /tools/package/bin/pnpm.cjs store add " + " ".join(
            paths[index : index + 32]
        )
        rows.append(command + " --store-dir /cache/store >>/scratch/import.log 2>&1")
    rows.extend(
        [
            "node /tools/package/bin/pnpm.cjs store status --store-dir /cache/store >&2",
            "du -sb /cache/store >&2",
            "head -c 32768 /scratch/import.log >&2",
            "tar --format=gnu --owner=0 --group=0 --mtime=@0 -C /cache -cf - store",
        ]
    )
    return "\n".join(rows) + "\n"


def import_argv(root: Path, downloads: Path, tools: Path) -> tuple[str, ...]:
    return (
        "/usr/bin/podman",
        "--remote=false",
        "run",
        "--rm",
        "--name",
        NAME,
        "--label",
        f"nexus.builder.cache_import={NAME}",
        *_isolation(),
        "--cpus=2",
        "--memory=4294967296",
        "--memory-swap=4294967296",
        "--pids-limit=256",
        "--timeout=900",
        "--tmpfs",
        "/cache:rw,nodev,nosuid,noexec,size=2147483648,mode=0700",
        "--tmpfs",
        "/scratch:rw,nodev,nosuid,noexec,size=67108864,mode=0700",
        "--tmpfs",
        "/tmp:rw,nodev,nosuid,noexec,size=8388608,mode=1777",
        "--volume",
        f"{downloads}:/downloads:ro",
        "--volume",
        f"{tools}:/tools:ro",
        "--volume",
        f"{root / 'inputs'}:/inputs:ro",
        "--volume",
        f"{root / 'inputs' / 'resolv.conf'}:/etc/resolv.conf:ro",
        "--env=HOME=/tmp/home",
        "--env=NPM_CONFIG_USERCONFIG=/inputs/offline.npmrc",
        "--env=CI=1",
        "--env=PNPM_DISABLE_SELF_UPDATE_CHECK=1",
        "--entrypoint=/bin/sh",
        IMAGE,
        "/inputs/entrypoint.sh",
    )


def _isolation() -> tuple[str, ...]:
    return (
        "--pull=never",
        "--network=none",
        "--http-proxy=false",
        "--read-only",
        "--read-only-tmpfs=false",
        "--image-volume=ignore",
        "--no-hosts",
        "--no-hostname",
        "--passwd=false",
        "--no-healthcheck",
        "--log-driver=none",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pid=private",
        "--ipc=private",
        "--uts=private",
        "--cgroupns=private",
    )
