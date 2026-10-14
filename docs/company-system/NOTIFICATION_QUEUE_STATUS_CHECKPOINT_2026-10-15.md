# Targeted notification queue-state qualification

Checked2026-10-15 after actual positive atomic enqueue1PG/9.41s. Independent
review found exact canonical terminal DBOS rows could report existing because
generic enqueue conflicts preserve status and its readback pins omitted status.
The targeted notification service now locks actual same-transaction status after
canonical command/ABI/input binding and before all final native/source/recipient/
credential/approval clocks. Only literal ENQUEUED/PENDING counts as active identity.
Terminal, DELAYED, missing or unknown status denies; no resume/refund/newID.
Generic scheduler and queue SQL remain unchanged.

Retained public-service terminal replay test failed1/1.34s before correction.
Frozen4 SHA f8c4c978f2463e1b8f602d8609c33b2c0df7d128a2f7d2a815b18f793003404c
records the correction, flow ordering and strict state tests. Author58focused/
1.68s/types/Ruffformat4 pass; Root19status-flow/1.26s and strict4 pass. These are
pure metadata/transaction mocks; actual cancelled DBOS row denial is pending.
Root coherent2,053unit/21.05s/19existingwarnings also passes; all frozen hashes
and retained logs independently match.

The next case uses public DBOSClient.cancel_workflow_async only for its actual
exact fixture ID, explicit restricted database/app, listener/retry disabled and
owned client destroy. It starts no DBOS worker and does not seed status SQL.
Previously committed decision/positive hold/native mapping/canonical cancelled
row must remain unchanged after denied replay. ActivePENDING race, postqueue
actual expiry/conflicts and durable dispatch/recovery remain separate gates.
