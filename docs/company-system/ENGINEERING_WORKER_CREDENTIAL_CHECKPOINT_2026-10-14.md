# Engineering worker credential and known-output qualification

Checked 2026-10-14. Fixed engineering.change/verify procedures are implemented,
but actual DBOS workflow execution and process restart remain unqualified.

The worker resolves the exact permanent dispatch/current plan/action, verifies
the actual signed UUID credential using the existing sealed verifier, and retains
its identity/expiry through source guards and final proof/acceptance/observation
clocks. Stores are constructed per operation; no token, reusable permit or expiry
DTO enters the portable command. Constructor-only optional witnesses preserve
existing uncredentialed acceptance behavior and require the actual lease actor.
The SDK uses a stable configured executor plus a fresh worker UUID and a bounded
one-worker queue; production polling is1s. No process is activated by this slice.

Actual known-output replay returns current protected accepted/unconfirmed evidence,
releases capacity and preserves M1 verifying, receipts, attempts and two positive
unknown holds. Source-resolution failure cleanup and the final source TTL gap were
reproduced and corrected (ERROR-085/086), with original logs retained. Current
known/cleanup/default3PG/29.34s, sealed expiry1PG/11.72s, foreign witness1PG/10.42s,
and final unchanged source probe plus known replay2PG/33.75s are separate overlapping
calls. Scoped3PG+7unit10/28.59s also passes. No totals are inferred from these calls.

Root hash-verified17files and staged16backend files into the qualified local runtime.
Its coherent combined suite passes1,696units/17.84s with19existing warnings. Source:
[engineering-worker-credential-freeze-1.json](/mnt/data/nexus-implementation-evidence-2026-10-14/native-builder/engineering-worker-credential-freeze-1.json).
Root type/lint receipts are saved alongside it. A later approved test-only pending
verifier fixture is separate from this frozen snapshot.

Required next: actual fresh intent/credential expiry before and after commitment,
pending verifier public setup, and five actual kill/wait/restart barriers. No new
effect may be issued for known/unknown replay. Full StockFlow, real provider/model
quality, ARM64, owner/email UAT, private deployment, independent disaster recovery,
rollback and24hsoak remain required. Goal active; no release promotion is claimed.
