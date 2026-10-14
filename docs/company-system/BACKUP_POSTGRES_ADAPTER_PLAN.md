# Operator-local PostgreSQL capture and matching restore

Approved bounded plan, 2026-10-14. Root created the exclusive disposable databases
nexus_company_test_backup_source and nexus_company_test_backup_restore. Production,
held UAT, Pi, provider and existing databases remain outside this package.

New server-owned LocalPostgresBackupConfig pins the fixed PostgreSQL17.6 binaries,
Unix socket/port/admin identity, exact distinct source/target names, company and
normal profile, bounded bytes/time and new protected restore root. It defaults to
disabled. Request methods accept no database URL/password, executable, arbitrary
SQL, schema filter, current clock, worker PID, grant or drained boolean.

PostgresBackupAdapter.dump(snapshot_id) emits a full custom-format archive from
the configured source, including DBOS schemas. restore(database) verifies a new
empty configured target and uses single-transaction/fail-on-error pg_restore;
it never creates, drops, cleans or resets a database. Process helpers use exec
without a shell, bounded streams/time, a tracked child group and complete reaping.
Child environment suppresses ambient password/service files. Errors expose only
fixed stage/reason codes, not argv, environment, archive bytes or stderr.

OperatorBackupCoordinator is injected with actual owner/current-directory reads,
registered immutable namespace readers, a trusted WorkerDrainProvider and opaque
KeyProvider. Capture accepts actual scope/identity only. It requires owner pause,
an acknowledged exit/wait witness from the exact registered OS worker handles and
quiescent native leases. Lease absence is insufficient. One exported PostgreSQL
snapshot supplies dump and all current/historical artifact metadata. Read exact
registered bytes, preserve namespace symbols/UUIDs and compare all schema/native
row fingerprints before/after staging to reject source drift. Keys never enter
configuration, argv, manifests or logs. Existing codec/tree contracts stay fixed.

The drill uses normal company migrations and actual DBOS migration only in its
new source fixture. Public native report/check services create actual artifacts,
receipts, held costs and attempt counters. A genuine registered DBOS worker is
paused at committed intent, killed and waited; source owner pause and an actual
lease expiry/release preserve uncertain effects. Full source+DBOS state is sealed
with a transient local test key, restored into the empty target and new protected
namespace, then compared before recovery. No raw operative pass/receipt seeds.

Recovery runs the same restored workflow on an explicitly TARGET-configured
runtime, not a checkpointed source connection. Verify target database identity,
target fence/ledger writes and unchanged source fingerprints. Require old-fence
denial, one retained attempt, unknown held billing and no provider/tool reissue;
known native receipts/artifact hashes and durable cursor/dispatch identities remain
exact. No hidden workflow/checkpoint/storage-reference rewriting is allowed.

Tests first cover disabled/config/foreign/nonempty target, malformed archive,
bounded output/time/process cleanup, source drift/missing bytes/owner pause and
drain loss. Actual restricted-role/native matching drill follows static checks.
Measure snapshot cut, capture/copy, data restore and safe workflow recovery
durations separately. Manifest capture_consistency/storage_independence stay
unverified; independent destination/key custody, service RTO and production/soak
qualification are separate gates. Root owns integration and existing codec/DDL.

## Verified local matching drill and retained state — 2026-10-14

The strengthened normal company_015/DBOS3.2 drill passed once in44.40s against
PostgreSQL17.6 with a restricted NOSUPERUSER/NOBYPASSRLS app connection. The original
worker actually reached committed intent, was killed and waited (exit-9), then the
normal lease expiry/reconciliation/release path left an unknown issued check.
Capture required current owner pause and the exact registered exited process.
The exported snapshot's complete table/artifact inventory matched the empty-target
restore before replay. The target runtime recorded current_database() as the
assigned restore database and replayed the same durable workflow without changing
checkpoint or native namespace references. It retained intent fence3, one tool
attempt, zero model calls and a USD0.03 unknown hold with no actual bill, receipt or
acceptance. The current work fence advanced5→7. The old lease was denied without
changing target facts. No publication/receipt/acceptance phases ran; source full
inventory remained unchanged. Source DBOS status stayed PENDING; target's same
workflow completed with the application outcome_unknown result.

Measured local capture1.692s, data restore2.127s and safe target replay7.140s;
snapshot age at final conservation check10.921s. These are fixture data/workflow
timings, not service RTO or disaster RPO. No independent device, key custody, lost
source, old backup, actual deployment or24hsoak was qualified. Restore presently
requires a live unchanged source and current owner pause; OPS02 remains open.

The source/target databases are preserved after terminal. The new test fixture
requires both empty before its first normal migration and never truncates,
downgrades, drops, resets or cleans them at teardown. Thirteen synthetic source,
restore and runtime files were copied byte-identically after terminal to the new
private home tree:
`/home/santapong/.codex/nexus-local-release-fixtures-20261014-continued/backup-matching-drill-1/preserved-run`.
Directories are0700 and files0400. Preservation receipt SHA
87b22b63f9ddc58f1a8c5260301204194c27cfd397ca1e1282d23855f9d42102.
The original drill ran under/tmp; its retained home copy preserves bytes without
rewriting database references. The AES test key and encrypted envelope were not
persisted; that transient bundle cannot be reopened after key loss. The restored
custom dump/artifact tree and authenticated descriptive metadata remain retained.

Seven subsequent retained-state read-only PostgreSQL cases passed in4.32s: each
second-drain company/source/PID/exit substitution denied, nonowner denied, nonempty
target denied before restore, and absent namespace/aggregate byte bound denied.
The comparison dependency is explicitly a controlled test witness; it does not
replace the original actual killed/waited process evidence. Separate metadata6
units passed2.38s and actual owned process-drain2units1.94s. Original adapter units16
passed33.67s; counts overlap later grouped checks and must not be summed as one run.

A synthetic TERM-ignoring descendant exposed a new process-group cleanup defect:
an already exited leader caused the old helper to skip groupKILL (1failed1.61s).
The owned helper now sends finalKILL to its exact child session group even after
leader exit. The unchanged reproducer plus the original process cases pass5/1.99s.
No unrelated PID/group is selected. This amended helper and extracted worker hook
postdate the full drill; the frozen final source needs Root integration review.
Original failure and fixed logs stay in backup-review. No shared codec/schema or
production/UAT/Pi/remote/provider changes occurred.
