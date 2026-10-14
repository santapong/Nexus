# Native report workflow integration plan

Checked 2026-10-14 after local checkpoint `da013b5`. Root owns the new native
worker and acceptance reconciliation modules. Existing fake worker remains a
historical offline adapter. This plan is not execution evidence.

## Concrete behavior

1. Actual owner-approved plan registers bounded author/verifier work with current
   mandate/charters, explicit source/output permissions and lifetime quotas.
2. Server preparation renders a saved native operating report from actual protected
   source bytes and current immutable facts. Exact action parameters bind report,
   recipe, output hash and complete input snapshot. Approval waits release capacity.
3. A stable native dispatch enters a registered DBOS workflow. Its one non-retrying
   step resolves a preverified configured actor, rechecks dispatch/workflow/catalog,
   claims a current fence and performs fresh M1 authorization/intent checks.
4. The native publisher commits exact artifact/provenance metadata after bounded blob
   preparation. The worker records an actual result receipt with the exact artifact;
   local deterministic compilation has zero provider usage and zero external charge.
5. A distinct registered verifier resolves that real author receipt, independently
   recomputes source/time/status/ledger checks, publishes protected check bytes and
   records its own actual check receipt. Only trusted proof publication produces
   `WorkAcceptance`; no model/candidate/DBOS return becomes company acceptance.

## Recovery invariant

Existing `recover_dispatched` intentionally grants only reconciliation capacity
once an intent or receipt exists. Native publication remains execute-only.
Missing published output after intent stays unknown; it does not re-render or
republish under a cached permit. A known exact protected artifact may resolve an
unknown receipt through existing reconciliation after current authorized reads.

An explicit acceptance-reconciliation path resolves the original successful
verifier check action, paired author selector, result artifact and immutable receipt
under the current fenced reconciliation lease. It independently recomputes the
actual target and protected proof with current governance, permissions and source
freshness. It appends or exactly replays acceptance without a new artifact, intent,
attempt, receipt, cost reservation or refund. Cancellation/revocation may deny new
acceptance while leaving historical issued receipts/costs intact.

## Validation before integration review

- Real public plan/action/source/publisher flow through actual producer and validator.
- Actual DBOS durable queue/process execution, stable portable dispatch/version pins.
- Crash after intent, artifact publication, check receipt and acceptance; restart with
  the same dispatch, no duplicate native publication or reset quota/charge.
- Missing result stays unknown; wrong author selector/result/hash/workspace/actor,
  stale source, revoked permission/governance and fence conflicts deny recovery.
- Final grant/lease expiry after awaited lookups/writes denies atomically, including
  exact replay. Unknown billing remains held; native local compilation has no model call.
- Strict types/lint, appropriate unit/PG checks, then one coherent independent review.

The full release still requires live provider qualification, real StockFlow readiness,
ARM64 builder, owner session/browser, email/private operations and recovery/restore.
