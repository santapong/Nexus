# Public runtime dependencies restored — 2026-10-15

The public dependency stage is complete and independently verified. The actual
download finished in **46.04 seconds**: 517 pinned package archives (193,711,174
bytes) and pnpm9.12.0 (4,542,556 bytes). This restores download inputs for a separate
offline cache rebuild. It does not establish cache availability, Node execution,
StockFlow timing or engineering acceptance.

## Inputs and actual outcome

The retained package manifest is unchanged: SHA256
`06ef2805b73fa8cae5ea93cbb6c857f6abe93773c1de9ed71603a3081cfce6ae`.
The private operator uses backend868d0dc, byte-identical to backend651fd82, with
two outside scripts; there is no production backend change. All 1,578 source pins
were checked before the released invocation and after completion.

Only exact retained HTTPS URLs at registry.npmjs.org were fetched, with TLS,
`trust_env=False`, GET-only policy and request-time removal of Cookie,
Authorization and Proxy-Authorization. The package cap stayed at
**536,870,912 bytes (512MiB)**, plus33,554,432 bytes for pnpm;900/120-second
transfer bounds,30-second finalization and an external1060-second stop envelope.
These accepted decoded-file caps do not measure total HTTP wire traffic.

Independent file audit recomputed every package SHA512 SRI, SHA256 and byte length,
plus the exact pnpm SHA256/SRI. All518 receipt rows match in order. The exact tree
contains520 ordinary files and two directories, with no extra, temporary or symlink
entries: UID1000, directories0700, files0600 and one link per file. The reviewer
read198,253,730 archive bytes and performed no extraction or execution.

## Preserved failures and corrections

The first held operator's credential-free policy did not exclude cookies supplied
by the server. Five actual MockTransport regressions reproduced this before the
request hook correction;28 tests then passed. Independent review checked the
pinned HTTPX0.28.1 ordering. Production downloader APIs remain unchanged.

The first real invocation stopped in0.606 seconds before reaching its first fetch:
the `/mnt/data` FUSE volume created the requested0700 stage as0755. Its empty stage,
source, release and failure logs remain preserved. No permission predicate was
weakened. A fresh same-parent Linux-filesystem probe proved0700/0600, then a new
path-only packet used `/home/santapong/.codex/nexus-runtime-public-stage-20261015-2`.
The previous packet was not retried or resumed. See ERROR130–131.

## Receipt identities

Evidence root: `/mnt/data/nexus-implementation-evidence-2026-10-14/stockflow/`.

| Artifact | SHA256 |
| --- | --- |
| Frozen v3 source manifest | `4289a66f3381232f926609ec0742384ff3d9ba23a3c8c33f9975f8d011683210` |
| Closed v3 packet | `a0bc0e163ab2f9fbf5989c14d95b29b2df75fb40c59b71dfd15ed58eb96fe59e` |
| Independent preflight file review | `9b043a01217c2a459df434505f56b0bfcbacf1e73b134ebb1c261bb6f2e8f554` |
| Root release2 | `00d18fe9a45092d7663ce8b40876aea9e05864bfe769c47cd93279420d903247` |
| Root terminal2 | `daddbe17a09c5c19678a9c3284c31e74ab4de465f13f75cc9082ab332e574b06` |
| Actual download receipt | `22916ff99fec736f7fac7bfd7d27aa30a9dcea0e0180021013215026a1d4f9e2` |
| Independent terminal file audit | `d998d7b8523434e50fca1fec17ba82e9d44cb5d68986a7a593f2b3a47fc57898` |

Next is a separately qualified host-side offline cache bootstrap with genuine
process containment and exact owned cleanup. If the rebuilt archive differs from
the original cache pin, a new runtime preparation, policy and E/EV templates must
bind its actual bytes before fresh company inception. No image pull, container,
service, database, model, email, Pi or deployment action occurred in this stage.


## Subsequent offline tool preparation

The unchanged bounded `extract_public_tool` helper extracted pnpm into the fresh
managed path `/var/tmp/nexus-runtime-public-tools-20261015-1/tools`. The outer
root also holds copied, reverified pnpm and package-manifest archives. Every one
of901 tool files matches its pinned archive entry (18,213,449 expanded bytes).
Independent file audit verifies the exact904file/237directory tree, copied inputs,
ownership and private modes. The tool receipt is
`0c33eb439630bada3ac58ef8d89d38dcd7d3346da5d9b680b055e4eb74c6a1bf`;
independent audit is
`02732fbe9579cf8dc09f6591ab1a2ec4a1f6f9af73cbde8b9826c722aaba9503`.

Root observed extraction process exit0 and34.13-second helper work. No independent
outer timing or process-containment witness was captured for this data-only step.
The outside-HOME location preserves the native Node managed-path requirement.
Neither pnpm nor Node was executed; cache import and actual runtime remain open.
