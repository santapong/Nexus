# Immediate engineering restart qualification packet

Date:2026-10-15. Proposal only; no new databases or processes are created by this
packet. All five earlier process databases and both matching backup pairs remain
preserved. The new helper/context source requires Root review first.

Exact proposed new cases:
- nexus_company_test_engineering_immediate_intent →
  /tmp/nexus-engineering-immediate-intent-20261015-1
- nexus_company_test_engineering_immediate_receipt →
  /tmp/nexus-engineering-immediate-receipt-20261015-1

The same existing private PostgreSQL17.6 Unixsocket55438/admin/app role is used.
Root creates each fresh empty database after review. Normal company015 and actual
DBOS3.2 migrations are followed by the existing genuine public pending verifier
fixture, actual owner authorization, protected source/patch and atomic scheduler
reserve+enqueue. No native/DBOS row seeds, no oldworkflow reset or hidden input
rewrite. Fixed same application/queue/executor are reconstructed in the restarted
worker; each process gets a distinct workerUUID. Source/config/image pins and
actualSegmentCommand/workflow identities are reviewed per case immediately before
launch; require ≥180s genuine source TTL. No source/credential/approval extension.

Test-only process scope mapping must append these two exact DB/root pairs. The
fixed reviewed entrypoint/controller may accept only this expanded closed set;
portable payload remains the exact SegmentCommand. Fresh source-only local snapshot
uses qualifiedHOMEpython; builder mounts remain owned0700/tmp and config/command
0600. Preserve exact source/action/spec/config/image hashes and raw receipts in a
privateHOME byte-equal copy afterterminal. No key/token is written to config.

At intent_committed or receipt_recorded, parent verifies actual original worker
lease still live under database clock, exactsame segment/workflow/input/native
intent and one toolattempt. Kill and wait only that recorded owned process. Then
IMMEDIATELY launch the same workflow without a barrier; DO NOT poll/wait for old
lease expiry in the controller. Query native DB immediately to prove old lease
is still live when the restarted process starts. Observe the restarted worker's
new acquisition helper continuing within the one process/handle (its preflight
must validate actual permanent dispatch/fullcommand/current member/credential),
then actualnewfence after nativeleaseexpiry. No provider/tool/model/effect retry.

Positive expectations:
- Intent death: one original intent/toolattempt/positiveunknownhold, zero containers
  bothprocesses, no receipt/proof/acceptance, sameworkflow/dispatch/run/segment,
  acquired/releasednewfence and honest historicalunknownresult. Source expiry may
  deny new publication but never cause a second effect.
- Receipt death: one actual originalcontainer, exactimmutableSUCCEEDEDreceipt and
  result/witness, current fullprotectedproof/acceptance under validsource/credential,
  zero secondcontainer/tool/modelattempt, positiveunknowncost retained, currentlease
  released and exactownedstoppedcontainer cleaned by immutableID.

Negatives use separate new legitimate fixture occurrences when needed; no resetting
these retainedpositiveDBs. Pure acquisition tests already cover finite310s total
wait (shorter injected test constant), cancellation whilewaiting, permanent denial
with no exactlive prior lease, and credential expiry afteractualacquisition releasing
the acquiredlease. Additional real restrictedPG tests must show current member
revoke/foreigncommand/differentsegment/credential expiry duringwaiting deny without
acquiring a new effect or changing original attempts/holds. A cancellation observed
while waiting leaves original prior worker lease to expire normally and must not
start another process. Distinguish a bounded acquisition wait from any effect retry.

The old manually sequenced fiveOSreceipts remain valid for their explicit sequence;
these new cases alone can close automaticimmediate-restart qualification. A fixture
failure/expiry/mismatch stops this wave and is preserved. Do not silently replace
that failure with a newworkflowID or source refresh.

## New restricted PostgreSQL negative fixture proposal

Exact additional disposable database:
`nexus_company_test_engineering_immediate_negative`, with temporary scratch root
`/tmp/nexus-engineering-immediate-negative-20261015-1`. Root must create/authorize it
before use. Test teardown may return only this newly disposable fixture to normalbase;
no retained process database is downgraded. Source uses qualified local source copy
and all current helper/context hashes below. Actual public setup uses the existing
pending scenario, native permanent dispatch and ordinary current execute lease.

For unissued live work, owner pause, permanent WorkCancellationStore.cancel,
mandate/charter revoke or whole source READ revoke must cause preflight denial while
the old exact lease is still live; zero new recover call/effect/attempt/refund.
Current member revoke denies both fresh and issued wait. A foreign full command or
different live segment denies despite any matching task ID. Actual credential
expiry during a nominated acquisition wait denies without refresh/new permit.
Prove the waiting hook is reached for temporal/cancel cases and preserve actual
native prior lease, intent/hold/counters rather than changing them to make a test
pass. Issued negative/positive scopes use genuinely committed original intent or
succeeded receipt, not raw effect rows. The helper separately verifies actual
JournalAction proposal hash and action/task/trace/actor binding, plus the issued
intent task/trace/run/proposal binding before historical waiting is allowed.

Current unit scope is13pure cases over a signature-verified synthetic witness and
controlled DB adapters: exact wait→one acquisition, permanent preflight/foreign
command/segment/member denial, cancellation waiting/acquired, finite total deadline,
credential expiry afteracquire exact release, internal DBtimeout preserved, fresh
pause and issued-splice denial. These are not restrictedPG or OS restart receipts.

Before classifying an exact command as fresh or historical, the helper now checks
actual unresolved intent/outcome_unknown identities in the same company/task/run.
Any different unresolved action denies; a limit2 query cannot hide ambiguity because
the exact action ID is unique. This follows the native runtime's broader issued
basis conservatively, without adopting another action's outcome or creating a new
segment. A pure other-unresolved-action negative is included in the final14case
matrix. The new restrictedPG fixture must reproduce this with genuinely issued
public actions; immutable seed edits are not proof.
