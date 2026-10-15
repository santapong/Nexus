# Pi builder preparation — 2026-10-15

Read-only checks find the Pi reachable, lightly loaded and running its production
services. The proposed builder is not ready: memory control is disabled, the
rootless container tools are absent and its systemd257 user manager has no current
Nexus qualification. No installation, configuration, service or reboot action
has occurred during this preparation.

At inspection, Prometheus, Resume and Ruview probes return HTTP000; they were
not diagnosed or changed. Serve and Funnel status both report tailnet-only
routes, with no public Funnel shown. No urgent host repair is inferred from
the builder's missing prerequisites.

The Pi is ARM64/Debian13 with kernel memory-controller support, but actual boot
arguments disable it. A source-supported candidate appends exactly
` cgroup_enable=memory` to the existing176-byte firmware command line, preserving
its bytes and lack of trailing newline. The197-byte candidate has not been
written. Actual postboot controller availability and enforcement remain required.

`/var/tmp` is a256MiB tmpfs and `/tmp` is512MiB. Neither can hold the proposed
cache. The persistent ext4 root has about84.5GB available at inspection; the
Seagate-named service path uses that same root device. `/srv/nexus-builder` is
an absent candidate directory, not an existing builder installation.

## Package preparation

The normal resolver selects nine new packages when netavark is requested
explicitly with the five core tools: Podman5.4.2, conmon2.1.12, crun1.21,
uidmap4.17.4, fuse-overlayfs1.14, netavark1.14, containers-common/image and libsubid5.
It selects zero upgrades/removals and leaves99 packages unchanged. The exact
archives total25,575,132 bytes with99,916KiB declared installed size. This omits
the unnecessary CNI plugin package from the preserved first ten-package plan.

All ten original public archives were fetched onto the laptop and verified
against the signed cached Debian index; the nine-package choice is a subset.
Bounded static review preserves maintainer scripts, triggers and relevant unit/
config text without executing them. Cached signature provenance is verified;
metadata was not refreshed and does not establish current repository freshness.

Installation has effects requiring a concrete plan. Netavark scripts request
three unit enables/starts; the installed helper preserves administrator masks
when its own mask marker is absent. Three persistent masks plus list-only
needrestart mode are source-supported candidates, still unapplied and untested.
Podman adds Quadlet generators and tmpfiles rules; uidmap adds setuid helpers and
libsubid5 triggers ldconfig. No claim of zero service impact is made.

The Podman CNI conffile is absent, confirmed by a single authorized privileged
metadata check. Its existing parent directory is0700 while the archive declares
0755; mode preservation must be explicit. Several default Quadlet input locations
are absent, but root-home/other-user/override locations remain unresolved. Their
activation must be resolved or prevented before installation/reload/reboot.

| Preserved evidence | SHA256 |
| --- | --- |
| Initial readiness | `95fe2af02ee4c8d85cdc5aa819881ffa21c728e3b6333e0ac5f1bd98660aa4b1` |
| Laptop archive acquisition | `e79607932ba19df37aecb5bde90ed6c655c28fb319579e4b76df8507b8ba5383` |
| Static archive review | `d0bedb7c2dcdc3d51b31ba089e21d448ef57cd5cfa6a4248f96012035299da6c` |
| Installed-helper correction | `728a0e859a7dee9cff9f08ef3b392c1ab61c6c8a235b4befc2002bf015632e09` |
| Nine-package comparison | `06f0c5cd2d4424ff6b5f542597e9d9155c12209af2f45002259bd56ffef281be` |
| Exact nine-package manifest | `e85ffc81b57355f89752861132326ce9d2bb03874fc06f17cbb4acfbc79ecdd3` |
| Conffile/Quadlet addendum | `f6cb193e485b1fd2d716d812bb88712cf1984fc54d1bdb37b382a6fd0f2d1680` |

The first static report's blanket warning about premasking is narrowed by the
installed-helper supplement; both immutable reports are retained. Next is a
reviewable install/boot/backup/rollback packet with explicit service disposition,
recovery access and an owner-approved reboot window. ARM64 image/CAS, manager257
profiles, finite resource/cancel/network/disk proof and native Company execution
require separate actual qualification after setup.
