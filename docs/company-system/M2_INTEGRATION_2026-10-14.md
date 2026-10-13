# M2 Brain integration checkpoint

**Checked:** 2026-10-14, Asia/Bangkok. **Source:** feature/company-foundation after local M1 bbd3d82; current M2 changes uncommitted. **Status:** persistent components individually validated; full M2 acceptance remains open.

## Schema, identity and permissions

Normal company008 adds26 Brain tables to the17-table M1 profile. Fresh install/repeat/all43-table metadata comparison/downgrade passes1 real PostgreSQL case. Every new table has forced native-UUID company RLS. Immutable source/artifact/parse/evidence/claim/relationship/derivation/event history is separate from current access/heads/cursors. Current identity and generations cannot be silently replaced or rolled back; one parser recipe cannot have both immutable success and failure. Verified outcomes and receipt/verification UUID promotion are deliberately blocked until a real independent publisher exists.

A company-first composite primary-key test failed before the mixin ordering correction. Static reviewed FK indexes and deferred cyclic constraints are included in the migration. Original merged legacy001–016 and company001–007 remain unchanged. Metadata compilation alone was not counted as deployed schema proof.

Root current-access checks pass7 real database cases: owner has no implicit source grant, stale CAS cannot regrant, revoke/history/outbox commit atomically, current membership and signed scope cannot be impersonated, expired grants/spliced work fail, and direct application SQL cannot bypass RLS/history guards. Six additional deployed-schema cases verify all26 forced policies, raw outcome/UUID denial, non-null parsed-offset pairs and both parse outcome orderings. These use only the private brain_access database.

## Individually verified components

| Component | Executed evidence | Limit |
| --- | --- | --- |
| Shared Brain contracts/metadata |58 initial focused unit cases; company-first metadata4 | No runtime score from structural validation |
| Ingestion/parser/blob/derivation/outbox |36 checks:20 unit +16 restricted PostgreSQL,32.16s;88% parent-process coverage | Child parser executes in an isolated process; its lines are not measured in parent coverage |
| Retrieval/context/artifact |20 checks:10 unit +10 restricted PostgreSQL,23.28s | FTS/exact IDs/closed graph; vectors/reranking disabled; Thai semantic search unqualified |
| Signed Brain API |9 initial HTTP/database +revocation/graph checks; optional real factory integration2PG +5unit pass4.37s | Brain is optionally mounted; default execution intake stays disabled |
| Brain-to-model authorization |Final30 checks:13 binding unit +17 PostgreSQL/offline SDK,39.84s, including source/approval expiry; default model45 checks26.75s | Explicit estimator/profile/recipe remains necessary; no live qualification/default provider |
| Committed Git source reader |12 unit checks,0.73s | Exact registered company/source/path/commit/blob/SHA256; no checkout/fetch or caller-selected ref |
| Whole unit snapshot |847 passed,19 existing warnings,14.35s | Subsequent active publication/evaluator packages require their final focused and integration checks |

Final whole unit snapshot:847 passed,19 existing warnings,49.49s. After the
shared expiry fix, execution/recovery33 pass23.68s and governed client21
pass21.51s. An unrestricted strict whole-source type invocation found only10
missing optional legacy dependency imports in6 files (OTel, Langfuse, Stripe,
Temporal, E2B) absent from the thin target environment. Existing CI already uses
--ignore-missing-imports; that exact command passes434 source files, recorded separately. Do not
claim type conformance of those absent optional SDKs from it. Changed Brain/
company packages have separate strict author checks. Initial final Ruff/format
found two owned test formatting issues, subsequently corrected by their authors.

Counts overlap and are not summed. Strict types and Ruff pass the frozen author packages; current combined checks wait for the active publication/answer packages. CI now has24 isolated company PostgreSQL matrix groups; YAML/test paths validated, no remote CI run claimed.

Protected blob reads happen outside the company lock. Final publication rechecks current directory/work, resource grants/expiry, complete contributor intersection, source heads and exact raw UTF8 bytes/hashes. Current-search handles cannot become historical implicitly. Context includes actual attachment/workspace text, source dates and authorized omissions; classification is the maximum of trusted runtime and all source contributors.

The trusted per-call context guard executes inside M1's current authorization transaction before and after bounded model/input validation, before intent or counters. The shared effect store then refreshes DB time, execute lease and exact/standing authority before mutation. It binds the exact rendered system/input strings, signed identity, work/lease/action, explicit model recipe/profile, classification and approved source preconditions. Source revocation/head/runtime changes deny issuance with billing/counters unchanged. Revocation after an already-issued SDK result does not erase its evidence, known cost or cancellation. SDK capture is separate from live model-quality evidence.

## Confirmed independent review corrections

The reviewer reproduced entity-own grant expiry during final evidence reads,
NULL parsed-offset persistence, source grant expiry during input estimation, and
exact approval expiry during the same estimator. Original independent probes
now pass after the production fixes; retained tests cover denial without a wire
or ledger mutation. ERROR-051/052 record the causes. The company mutex does not
freeze wall-clock time. Historical28-case context-gate receipts predate these
corrections; final30-case evidence supersedes their source snapshots.

A fifth current-entity stale-classification issue after source R1→R2 is closed: the current endpoint rejects stale/history support, while explicit historical citations stay labelled. The original independent probe passes1case5.25s; retained graph/expiry/staleness3cases pass9.07s (ERROR-054).

## Nominated real product source

The [source manifest](STOCKFLOW_SOURCE_MANIFEST_v1.json) selects bb7cc00848bb650069543e843f826703d468058c. Five exact Git blobs,223885 bytes, passed actual protected ingestion, exact duplicate replay and restricted SQL retrieval/materialization. Their source-event timestamp is the commit's2026-09-01T13:56:41+07:00; server ingestion is separate. The proof uses synthetic authenticated test identities with actual product bytes. It establishes immutable code/document source access, not a deployed revision, customer readiness or company operation.

Raw proof/logs: `/mnt/data/nexus-implementation-evidence-2026-10-14/stockflow-real-source/proof.json`, `stockflow-real-source-bounded.log` and the preserved probe script. An initial probe omitted mandatory server RetrievalLimits; another four-term AND query correctly returned no match. The final probe uses explicit OR semantics and bounded5 results. This is not a natural-language/semantic recall benchmark.

The Git adapter's first large-stream test exposed partial reads and an unread PIPE wait; that old process was terminated after confirming its exact owned PID. The corrected bounded EOF drain and child-output cleanup pass the12-case package, including multibyte content and oversized-pipe denial. No shared process or service was terminated.

Three distinct actual permission-filtered SQL queries were captured with their
unchanged bound parameters and executed under EXPLAIN (ANALYZE, BUFFERS, FORMAT
JSON), on the same restricted company scope and five real product blobs. Recorded
execution times were26.333ms,0.4ms and0.575ms; this tiny snapshot is not a large-data
performance claim. SQL fingerprints and full plans are in
`stockflow-real-source/query-plans.json`; log `stockflow-query-plans.log`.

The whole post-change unit suite passes847 cases with19 existing warnings; the
actual DBOS worker's10 process/database cases pass75.58s after the shared effect
expiry correction. Original independent review has closed all five confirmed
production findings. Publication6source/8test/4log hashes match the final acceptance manifest2a71d036...; the independent reviewer approves the scoped offline foundation after all five original probes close. This is not M2 answer or release approval. The separate scorer review independently recomputed the saved first receipt exactly from29 hash-verified observations:17/30,14/16critical, threshold false. Its receipt SHA256 is880d3172a985e7293cf115ece787334520fe4a8597bb5354a2852a99fb6bc37b.

## Remaining M2 and release work

Claim/ontology publication passes30 focused real/unit checks with93% coverage of505 new statements; its frozen combined review is approved for the offline foundation. It validates exact evidence, active actor/owner scope, output-reader intersection, immutable revisions/CAS and bounded supersession. The separate source/golden30-case pack is unchanged. Its first source-derived offline baseline scores17/30 and14/16critical, failing the unchanged ≥27/all16 threshold. The observer driver itself passes29 cases and fails B06 capture; that pytest count is not the answer score. The full first receipt/matrix/observations are preserved in brain-api/original30-first/. The evaluator must observe independently produced structured answers and actual SDK inputs; prompt inclusion alone or copying expected answers cannot pass the gate. Full M2 requires ≥27/30 and all16 critical rubrics, combined provenance/permission review and real-source acceptance with explicit limitations.

M3–M6 remain: actual management/plan/scheduler, native ARM64 builder, full StockFlow cycle, dashboard/email, private authenticated access, independent backup/restore and operational recovery/release. The full release goal is active. No paid model, connector/vector activation, external notification, Pi service mutation, push/tag or deployment occurred in this checkpoint.

## Offline exit — subsequent verified checkpoint, 2026-10-14

The earlier first17/30 failure remains historical evidence. Second29/30 andall16
critical satisfies the unchanged offline threshold; all30 observations and14
freeze5 code hashes match and the separate scorer recomputes exactly. B06 remains
visibly failed. [Offline acceptance](M2_OFFLINE_ACCEPTANCE_2026-10-14.md) consolidates
this answer evidence with the persistent schema/ACL/publication/context/API/model
and actual product-source checks. No live LLM quality, business completion,
management activation or full release follows from this milestone.
