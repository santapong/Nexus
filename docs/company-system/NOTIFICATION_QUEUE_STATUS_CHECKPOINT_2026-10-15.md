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


Before actual cancellation, independent pinnedDBOS3.2 review found publiccancel
sets CANCELLED and clears queue_name. The actual lifecycle probe must expect that
removal and retain exact other ABI/input/native history, rather than assert the
old queue remains canonical. Existing generic queue binding denies that cancelled
replay before the new targeted status helper; this case cannot claim the helper
was exercised. The retained pure canonical-terminal red/green tests remain its
specific boundary proof. No direct status/queue SQL rewrite is permitted.


## Actual public cancellation conservation

The corrected one-case fixture passed1PG/9.54s without correction/retry. Public
app-role DBOSClient cancels the exact native workflow, clears queue_name and keeps
remaining fixed ABI/canonical inputs. Replay denies at exact generic queue-ABI
check BEFORE the new status helper. Actual original decision/consumption/positive
HELDUSD0.010000/nullactual/native dispatch/counters/effect-zero remain unchanged.
No refund, new ID, status SQL rewrite, worker or HTTP effect.

Receipte84243fa1dcccf25a7c7c38edd868ecb5b239b5c30ae2d2fa3fecea2fdd352de
and private proofc694442d export actual before/cancelled IDs/hashes and client
destroy before normal owned teardown; appNOSUPER/NOBYPASS/normalbase/noDBOSschema
observed. Targeted canonical-terminal status-specific proof remains the retained
pure red/green cases; activePENDING race and postqueue expiry/conflicts remain open.
