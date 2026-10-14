# Genuine receipt notification checkpoint

Root freezes21 Python files:11 receipt/composition/tests plus unchanged10 native
draft/recipient files, recorded in receipt-root-checkpoint-source.json. Base05513f0
stable snapshot excludes active dispatch/newkind/Node work. Whole1321unit pass32.96s
with19 existing warnings; Root strict11 and prior draft strict10/lint/format pass.

Configured EffectStore appends ID-only failed receipt events under the same actual
CompanyControl transaction as native outcome/cost. It re-reads persisted work/intent,
requires session-owned rows and exact stored action/actor/run/trace/receipt/proposal
and registered real resource. A transient invented failed row is rejected. Existing
known receipts coalesce the same event without new attempts or costs. The hook
cannot mint work, approval, allowance, execution or an external call.

Native report composition explicitly supplies the catalog publisher. Default None
keeps original standalone M1 behavior. Already-issued outcomes remain recordable
after company pause or source READ revoke; private source bodies are not accessed
to publish the IDs. The owner draft reader separately checks current source/resource/
recipient permission and deadlines before exposing details. Final lease/fence after
hook awaits and final flush rolls back receipt/cost/event together on expiration.

Root combined12restricted normal015PG67.33s: actual cached-image failed builder
process→failed native receipt→one durable wake→current licensed owner draft; replay
conserved attempts; transient/config/conflict denial; natural final lease expiry;
post-issued pause/revoke recording; nonfailed no wake; actual native report
composition. Synthetic recipient and controlled failure fixtures are labelled;
the real failed process is separate from lower-level outcome transaction fixtures.

Independent read-only review matched21/21 hashes and reran unchanged atomic(two),
transient and real failed process probes4PG23.65s; no additional actionable finding.
Verdict notifications/receipt-independent-review.json SHA9356e8442c16fd5ff8541e626300e3b3ee422ad2519d281b08ebf93b7f3fdebb.
Original unconfigured M1 execution13PG31.52s passes on a separate DB. Both DBs
are released after normal downgrade. No create_all/stamp or live service migration.

Retained failures: first process test guessed baseline_failed instead of actual
commands_failed; first source revoke guessed ACL generation1 rather than actual
resource generation. An early expiry fixture incorrectly expected renew to shorten
an existing lease; the actual short initial lease reproduced and closed the hook
clock issue. Original false transient-row and actual-clock failures remain in
receipt-transient-red.log/receipt-clock-real-red.log. No evaluator or source was
changed during independent review.

51 configured CI groups resolve index paths. Receipt CI covers the11 database-only
cases; the real cached-image process case requires separate qualified local engine
setup, and its local proof is retained. Remote CI unrun. New meaningful wakes,
atomic notification cursor and managed sender/worker, live acceptance/delivery,
StockFlow/customer readiness, ARM64/private release/recovery remain required.
Separate dispatch review currently has an open post-intent target-revoke finding
(ERROR-072); that uncommitted package is not included or accepted here.
