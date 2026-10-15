# Strategy check receipt and acceptance integration

The next native boundary must record acceptance only from actual protected S/SV
facts. A raw passing result, immutable artifact row or caller-supplied target is
not sufficient. This plan complements the native bundle publication plan and
does not activate an effect, worker, owner transition or mixed-cycle admission.

The concrete StrategyInputReader resolves the unique current actual strategy
pair and original succeeded author receipt. Its `load_check_locked` returns the
VerificationSpec and original protected snapshot/output; `check_inputs_locked`
must return the exact current native M+B+Brief manifest and effective inherited
classification. All APIs use the caller's same CompanyControl-first transaction.

Root's separate `require_strategy_verifier_receipt` resolves the explicit actual
verifier_action_id. It binds the current execute lease/native work/verified
credential, immutable journal proposal, original succeeded intent and original
ExecutionAttempt/fence to the exact strategy check selector and protected result.
It preserves the old intent fence when the current lease is newer. Metadata must
follow intent issuance and precede the receipt. This gate returns facts, not a
verdict, current plan authority or protected READ permission.

`StrategyCheckProductionSnapshot` binds the actual resolved target, original
snapshot, exact author output and full M+B+Brief manifest. The check action's
input_snapshot_sha256 must equal this complete identity. The mechanical result's
input_snapshot_sha256 remains the original S snapshot digest. Never confuse the
two or refresh the original snapshot's clock. Deterministic check bytes are
recomputed from the actual reader's command; no supplied PASS/self-consistent
result hash can replace that comparison.

Proposed concrete `StrategyAcceptanceStore.publish_verified_result(lease,
identity, *, author_action_id, verifier_action_id, protected_result, credential)`:

1. Enter the native runtime transaction, current execute lease and exact signed
   verifier scope. Re-resolve current pair/target, protected original B/Brief and
   complete check manifest through the configured concrete reader.
2. Require the actual succeeded SV journal/intent/attempt/receipt/result binding.
   Revalidate current protected check READ, entire derivation/input graph and
   registered recipe/policies/classification. Read exact bounded locked bytes;
   compare recomputed bytes and both original action input/output hashes.
3. Build a strategy-specific immutable WorkAcceptance identity keyed by the exact
   actual target, with its proof bound to the protected result. A previous record must match full target,
   proofs, verdict and limitations. Reuse existing acceptance/proof tables and
   immutable encoding; no raw verification API or new table is required.
4. Append acceptance/proof/event rows in that same transaction. After the last
   flush/lookup, re-resolve current pair/target, original sources and saved result
   as needed; then take the final actual database clock. Check all initially and
   currently captured source/grant/profile/approval/lease/credential windows with
   no later await before exit. Any failure rolls back all new proof rows/events.

Known exact acceptance replay does not issue another effect, charge or tool/model
attempt. Execute publication and reconciliation recovery remain distinct paths;
reconcile support requires a separately reviewed actual-receipt recovery method.
Do not call an execute-only publisher to repair an unknown effect. Unknown billing
stays positive held/unknown with null actual unless genuine billing evidence says
otherwise. Mechanical acceptance does not certify strategic merit or business
readiness and does not complete M1 work by itself.

Qualification must use a fresh exclusive normal015 application-role fixture after
the complete publication/reader/check store source is frozen. Public source,
governance/plan/action/lease/intent/publication paths must produce real S and SV
receipts. Prove no-receipt/unknown/crossed-verifier/changed-result denial, original
fence retention, actual acceptance and current replay. An expiry/revocation after
the last awaited lookup/write must roll back every acceptance/proof/event row.
Only then can owner-choice revision2 and full StockFlow cycle integration proceed.
