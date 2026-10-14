# Matching encrypted company backups and disposable restore

Root-owned release work,2026-10-14. Implement a bounded operator-only encrypted
database/artifact bundle, then demonstrate matching normal015 restore and safe
unknown-effect recovery on dedicated disposable databases. This does not authorize
production dump, credentials, Pi/service changes or independent storage claims.

Files: new operations/backup contracts, sealed envelope, safe pack/unpack, protected
file I/O, PostgreSQL subprocess adapter and coordinator; focused tests and a local
qualification driver. Root owns explicit cryptography49.0 dependency/lock metadata
and ADR. It is already the installed/transitive pinned version; do not upgrade SDKs.

Encryption uses the installed AESGCM implementation, fresh96-bit nonce for every
seal,256-bit externally supplied key and authenticated format header. Verify the
tag before unpacking. The key never enters bundle, manifest, argv or logs. Tests
generate only ephemeral local keys. Pin direct dependency and reject wrong keys,
tampering, malformed/truncated headers and oversized input.
[Primary API documentation](https://cryptography.io/en/49.0.0/hazmat/primitives/aead/)
and inspected local49 API signatures support this method. Cryptographic behavior
does not establish capture consistency, operating key custody or storage independence.

The first bounded format supports at most256MiB packed/plain data and100000 files,
ordinary nonsymlink files only. Inner manifest pins exact dump bytes, artifact
relative paths/length/SHA, company/version/source time and capture limitations.
No traversal, duplicate/reserved names, links, special files or decompression
overflow. Restore verifies the complete bundle before writing into a new empty
protected directory, preserves immutable file bytes and never rewrites references
to make a different storage namespace appear equivalent.

Database capture uses normal PostgreSQL17.6 pg_dump custom format, fixed executable
and server-owned local connection configuration, bounded process/output/time and
safe error codes. Capture checks current owner pause/quiescent leases and records
the actual snapshot/source identity; staged artifact set/hash checks reject changes.
Unknown intents/holds remain unknown in the bundle. Worker drain and external
uncertainty cannot be inferred from a missing local lease; operational capture must
prove its own stopped workers/intake condition before claiming a consistent backup.

Qualification uses new isolated source/restore DBs, normal company migrations,
restricted application facts and explicit local admin restore only. Check exact
row/cost/counter/intent/receipt/source/artifact hashes and no reissue on recovery.
No create_all/stamp, fake operative receipt/pass, existing DB reset or held UAT
touch. Measure RPO/RTO for this drill; source/archive declaration is not recovery.
An existing target must deny before mutation. A failed restore remains explicit
and cleanup is limited to the owned disposable fixture, not production rollback.

Done: concrete encrypted bundle, exact matching disposable restore, retained unknown
outcome/allowance and failure/tamper/current authority tests. Actual independent
backup device/key custody, Pi/VPS private operation and24-hour soak remain separate
release gates. Estimated risk high (data loss/leak/false recovery); mitigate bounded
authenticated format, empty target, actual matching restore and milestone review.
