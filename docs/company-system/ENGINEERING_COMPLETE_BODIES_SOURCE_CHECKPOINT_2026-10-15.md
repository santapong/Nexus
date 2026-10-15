# Complete engineering bodies — source checkpoint

Subsequent [actual bounded reader SQL](ENGINEERING_COMPLETE_BODIES_PG_CHECKPOINT_2026-10-15.md)
passes28.18s. The source-only evidence below remains scoped as recorded.

Checked 2026-10-15, based on `e9ff56f`. Source/mock qualification only; actual
restricted SQL reads, measured timing and the real StockFlow E/EV pair remain open.

The previous private consumer rejected a valid complete result above 16 KiB because
its first public slice truthfully reported `has_more`. The retained reproduction
failed at that check before implementation. Engineering inputs now assemble the
complete body through sequential native reads, with each public page still limited
to 16,384 bytes. Generated proofs remain limited to 16 KiB; actual result references
remain limited to 262,144 bytes. This change does not enlarge those contracts.

The private process-local body retains the genuine first slice, full bytes and the
original qualified freshness. Every page must retain the same reference, source,
grant, head and classification metadata. UTF-8 endpoint splits allow at most three
same-offset retreats; other read denials propagate. Full length, SHA, UTF-8 and NUL
checks precede parsing. A body is bounded to 524,288 bytes, 33 successful pages and
132 attempts. One fixed 30-second ceiling covers the collection; it does not extend
any source, grant, credential or lease deadline or prove real timing feasibility.

Locked revalidation pairs the existing slice check with the full-reference stored
tail hash check. The complete loader, input revalidation and both acceptance proof
checks use that pair. Final original windows and reader composition are rechecked.
PreparedEngineeringInput keeps its four fields and genuine first ArtifactSlice
values. CompleteEngineeringBody is descriptive material, without a permission flag.

Validation:

- Author: 77 focused tests in 2.18 seconds; configured strict typing, Ruff and
  formatting pass for six Python files. All changed files remain below 400 lines.
- Root: **3,753 unit tests pass in 67.03 seconds**, with 19 existing warnings.
- Independent file review reports no blocking source finding. Source closure is
  1,573 base files plus three new files; exactly three existing files changed.
- Source manifest `6302cb762282caee55c343276746cc8e4332901a08dd1a1b3b8e358552cb9872`;
  peer `11843f8677511decc3bdeb66d0138aeef8f9d238d289e037a6ebd6219ae5d282`;
  Root receipt `113dc0da0b07894b06b68035bee9979ff7c1f3830d0e3fbf3243dfeb86bcaf14`.

Evidence: `/home/santapong/.codex/nexus-engineering-bodies-20261015-1`.
Next is a separately frozen restricted-SQL reader recipe covering real pagination,
READ revocation, original expiry, full-tail tamper denial and measured costs. No
native job, SDK worker, model/provider, email, Pi or deployment ran for this package.

## Separate mixed-sender SQL failure

The first B2b SQL recipe on unchanged `e9ff56f` failed in 90.64 seconds, before its
first begin/send. A fixture diagnostic incorrectly applied strict Python validation
to actual JSON-shaped action parameters. Its database and all original authority
remain preserved; the production validator was not changed. Root's read-only
terminal observation found one company, twelve work rows, two original S/SV
intents/attempts, no notification slot/observation, one ENQUEUED queue row, two
unknown holds and one held reservation. Application sessions were zero. The one
current N lease was retained at observation time; it was not released or renewed.

Root terminal receipt `51b978469f96068cf14f7f2a8909d5f8bdb53f1d1c58b64d8d56b000551e6158`
pins 31 prior run files. A fresh v2 namespace and strict JSON-boundary regression
are being prepared. Positive send, rollback, history, SDK and full-cycle gates
remain unqualified by this failed recipe.

Subsequent [fresh v2 direct SQL](MIXED_SENDER_B2B_PG_CHECKPOINT_2026-10-15.md)
passes189.23s. The original failure above stays preserved. This closes that scoped
synthetic direct-SQL gate; SDK/live email, reader SQL/timing and the real E/EV pilot
remain open.
