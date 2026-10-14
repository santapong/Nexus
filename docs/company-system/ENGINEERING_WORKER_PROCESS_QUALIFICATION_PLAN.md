# Engineering worker process qualification packet

Date:2026-10-14. Proposed; no DBOS process/barrier wave has launched. Root reviews
this packet before creating or using the five new disposable fixture databases.
Existing engineering_recovery and retained backup pairs remain separate.

Exact proposed database allowlist:
`nexus_company_test_engineering_process_intent`,
`nexus_company_test_engineering_process_result`,
`nexus_company_test_engineering_process_receipt`,
`nexus_company_test_engineering_process_proof`,
`nexus_company_test_engineering_process_acceptance`.
Each is a new empty normalcompany015 fixture on the existing private Unixsocket
/tmp/nexus-release-tests-2026-10-13/socket:55438, PostgreSQL17.6; admin santapong for
normal company+DBOS migrations, NOSUPERUSER/NOBYPASSRLS nexus_company_app for every
business worker connection. No create_all/stamp, no original database reset and no
full cleanup of retained databases. Preserve per-case DB/native/DBOS facts after
terminal for Root verification; assign new DB names for changed-condition retries.

Qualified runtime is
/home/santapong/.codex/nexus-local-runtime-20261014/bin/python. Stage exact repository
source-only files/config into a new hashed local/tmp tree; native builder prohibits
owner home bind mounts, so task-owned source/job mounts must remain new0700/tmp
paths. Keep process config/receipts/source copies and final evidence in a new
private0700home root, with post-terminal byte-equal copies of temporary job trees.
No keys, credentials, .pth, startup hook, live provider profile or private StockFlow
files belong in the fixture config. It records the actual fixed catalog, protected
source metadata/patch, policy/image, path mapping and exact approved native action
specs, not one-time permits. Root must review its exact source/image hashes before
launch. Filesystem path recovery never rewrites checkpoint input/native references.

A narrowly scoped existing TEST helper amendment is proposed:
`engineering_scenario(factory, root, *, reserve_native_dispatch=False, defer_verifier=False)`.
Defaults preserve original behavior. With defer_verifier=True, actual public setup
still registers the same new procedure/owner-approved author/verifier pair, runs
only the actual author bounded container to succeeded receipt, authorizes and
reserves the verifier's exact native SegmentDispatch, then returns the pending
actual verifier action/spec/source. It acquires no verifier lease and seeds no
receipt, result, proof, cost, acceptance, counter or outcome state. A NEW typed
pending fixture return should be used rather than making existing actual result
fields falsely nonoptional. Root must approve that fixture delta before editing.

Before launches, the existing scheduler enqueues the authorized pending verifier
using its registered engineering.verify/v1 ABI into actual DBOS schema3.2. Use the
fixed application nexus-native-engineering/v1, queue nexus.engineering.native,
stable executor ID nexus-engineering-v1-local and a distinct fresh worker UUID per
process. Permanent SegmentCommand and workflow UUID are identical across the killed
worker and restart. Child commands contain only fixed test roots/workflow IDs; DB
connection comes from the exact process environment with the allowed app identity.
Use no hidden checkpoint or source connection rewrite.

Five actual OS kill/wait barriers are:

1. intent_committed: observer at runner invoke entrance after actual M1 intent
   commit, before container invocation. Kill/wait; restart marks original intent
   unknown, retains positive held money and one attempt, publishes no accepted
   proof and invokes zero new containers.
2. result_stored: a trusted BuilderResultStore wrapper delegates durable save then
   observes. Kill/wait before native succeeded receipt; same-dispatch reconcile
   restores known result/witness/protected receipt without a second container.
3. receipt_recorded: EffectStore wrapper delegates actual receipt transaction then
   observes. Restart requires the actual verifier SUCCEEDED receipt, saved exact
   result/spec/witness and unique approved author receipt before current proof.
4. proof_registered: observe only after prepare_verified_result's actual protected
   proof transaction commits, not after staging bytes or before flush. Restart
   matches exact protected proof identity/derivation/input manifest and recomputes
   current source/membership/governance/fence windows before acceptance.
5. acceptance_recorded: observe only after actual atomic WorkAcceptance transaction
   commits, before lease release and DBOS result. Restart reads/revalidates the same
   acceptance, releases capacity, and preserves original known receipts, counters,
   holds and native references.

Hooks/wrappers are NEW process-local trusted instrumentation and never enter the
portable DBOS payload or grant a fresh effect. Generic NativeBuilderRunner code and
execute-only engineering acceptance APIs remain unchanged. The current NEW worker
must first pass actual services/context/known-output replay and source resolver
failure cleanup before this wave. Root reviews exact wrapper/store signatures.

Credential composition is now implemented through the existing sealed signed
verifier and per-operation guards/stores. Current known-output, lease cleanup,
foreign witness, final credential expiry and source-window cases are qualified in
ENGINEERING_WORKER_CREDENTIAL_CHECKPOINT_2026-10-14.md. Shared SchedulerIdentities
is unchanged. Actual fresh intent expiry before/after commitment remains required
before this process wave. Paused/revoked scope supports historical read-only audit,
not new acceptance. Do not launch the five-process wave until the fresh boundary
cases and exact pending fixture/action/configuration packet are reviewed.

For every case record actual current_database(), non-elevated role, native action/
run/segment/workflow IDs, process PID/exit+wait proof, pre/post source/protected blob
hashes, exact intent fence/current fence/attempt IDs and model0/tool1 lifetime
counts, positive unknown USD holds with null actual amount, same native dispatch,
actual DBOS workflow/step states, original receipt bytes, protected proof/acceptance
identity or explicit unknown result, current lease released/expiry outcome, exact
owned container cleanup and zero second invocation. Record command/source/image
pins and stage timings separately. Source/target/restored service RTO, independent
storage/key custody, StockFlow business acceptance, ARM64 and live credential/provider
quality remain outside this mechanical process fixture scope.
