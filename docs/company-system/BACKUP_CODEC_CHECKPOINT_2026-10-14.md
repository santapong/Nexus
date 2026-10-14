# Encrypted backup format and restore-tree checkpoint

Root coherent snapshot at250bb9a plus11 source/config/plan files passes1482unit
43.23s (19existing warnings), strict8/Ruff/format. Focused28 codec/path units pass
0.71s. Active gateway/engineering code is excluded. All runtime modules<300/new
functions<=50. Direct cryptography49.0.0 pin preserves every package version in
the offline regenerated lock; existing SDK/runtime versions stay unchanged.

AESGCM uses an externally supplied256-bit key, fresh96-bit nonce and authenticated
format/length header. Invalid key/tag/header/nonce/length/truncation/extra data
fails before plaintext return. Initial literal header length caused a roundtrip
failure; derived field lengths fix it and original receipt remains. The exact
[version49 primary API](https://cryptography.io/en/49.0.0/hazmat/primitives/aead/)
and installed signatures were inspected. The bundle contains no key material.

Authenticated plaintext contains only bounded ordinary ZIP members and complete
typed company/revision/dump/artifact length/SHA manifest. Unsafe normalized paths,
duplicates, links/special files, unexpected members, excessive file/expanded/packed
sizes and mismatched bytes deny. All bytes validate before a new protected target
is written. Direct typed restore also enforces aggregate expanded bounds. Manifest
capture consistency and storage independence remain explicitly unverified.

Independent review reproduced a target replacement race in the first writer: a
new empty target changed to symlink redirected output before its late final open.
Original local probe failed0.35s; fixed unchanged reviewer probe passes0.26s and
Root repeat0.17s. Parent/target FDs stay anchored before any write, directory walks
and leaves use nofollow relative access, private modes/fsync and final inode/visible
namespace checks. Existing targets remain untouched. No key/database/user paths
participated in that test; existing source/probe hashes and outside-write metadata
are preserved. No other proven crypto/archive issue was reported in the inspected
early scope. Whole lifecycle/drain/backup consistency is not part of this finding.

Evidence: backup-review/root-codec-source.json, root-codec-{unit,types,lint,format}.log,
source-original.json/source-fixed.json, original/fixed target probe receipts;
backup-seal-first/implemented/fixed and backup-files/codecs receipts in external
implementation evidence. This package creates no scheduled backup, database dump,
restore, credential, device/service change or independent storage claim. Normal015
matching disposable database restore, stopped workers/intake, unknown-effect
conservation, declared RPO/RTO and actual private operating deployment remain open.
