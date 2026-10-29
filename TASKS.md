# Nexus supervised delivery tasks

**Canonical tracker:** this file until the Waypoint trial is accepted and its
Nexus task records have been reconciled. **Coordinator:** the current Codex
session. **Resumed:** 2026-10-28, Asia/Bangkok, at the owner's request.

**Outcome:** DravenIQ's internal Nexus operates a supervised cycle from an
owner goal and evidence through an approved plan, authorized change, independent
verification, departmental outputs and an owner report. StockFlow is optional
later. Delegated/Board authority and automatic Meta Harness are outside the
initial supervised release.

**Acceptance:** the real Nexus cycle, signed-in owner journey, qualified
multi-provider usage and US$5 Bangkok-day controls, independent native builder
and ARM64 evidence, owner reporting/email, private operations, restore, rollback
and 24-hour soak pass their documented gates. Source checks and mocked calls
are not release acceptance. The repository's 80% coverage gate remains in force.

**Workflow:** Backlog → Ready → Active → Review → Done. A worker report enters
Review; the coordinator accepts it against the actual artifact and evidence.
Record a named blocker and next action in the relevant row. One owner per task;
only the coordinator updates this board and shared integration files. Model and
effort inherit the configured default unless otherwise stated. Start with at
most two concurrent workers, respecting the Nexus/runtime limits. Run one heavy
build, database, browser or test phase at a time under the service-test budget;
task counts are not proof of enforced CPU/RAM limits. Default task budget is one
attempt plus one diagnosis-driven revision; document any additional attempt.

| ID | Deliverable and acceptance | Owner | Dependencies | State | Evidence / next action |
| --- | --- | --- | --- | --- | --- |
| N0 | Reconcile current checkout, preserved local work, evidence and first source cohort; accept only confirmed identities. | Coordinator | — | Done | The resumed `feat/company-foundation` base was `1dcf415`; 73 pre-existing changes were preserved. Historical temporary receipts are absent. Fresh exact-commit source proof passed; 1,891 tested backend files matched the checkout at that checkpoint. The separately dispatched read-only Orca worker remains unconfirmed. |
| N1 | Trial Waypoint's project/task readback, dependencies, accepted evidence, stale conflicts and uncertain-create recovery in isolated fixtures; separately verify owner view. | Coordinator pending specialist | — | Ready | 28 October: ten isolated ASGI/PostgreSQL 17 checks and two additional real-ASGI/PG lost-response cases passed. Waypoint browser reached Google sign-in and was handed to the owner; owner view and Nexus migration remain unverified. |
| N2 | Verify owner setup and signed-in Knowledge → citation → saved goal journey. | Owner experience specialist | N0; owner password entry | Backlog | 28 October metadata-only inspection: invitation expired and unused, password absent. Local API and frontend ports did not respond. Restore/reissue only at the actual owner handoff; password entry belongs to the owner. |
| N3 | Validate current planner/coder version identity and complete a fresh integrated Nexus workflow with truthful accounting. | Coordinator | N0 | Done | Fresh v13 on the changed production source passed planning→coding→publication with two SDK mock requests. A separate restricted read-only rollback audit confirmed both reconciled synthetic costs totaling USD0.000004 and no live leases. V12's earlier 503 remains unexplained and preserved; live providers and native execution remain N5/N6. |
| N4 | Run combined source regression and meaningful same-cohort coverage at the unchanged 80% threshold; resolve demonstrated failures. | Coordinator with specialists | N0, N3 | Active | Repaired reconciled candidate passed 5,822 unit tests and two synthetic N5 PG integrations; exploratory combined coverage is 64.539840%, below 80%. Unit-run dependency bytes were not fully pinned. Add meaningful integrations and preserve earlier cohorts separately. |
| N5 | Qualify multiple providers, actual usage and persistent Bangkok-day budget control. | Coordinator with model-gateway specialist | N0; applicable live-provider authorization | Active | Fresh v4b private-PG tests passed for two mock providers with over-budget denial and for a separately issued unknown result with replay denied; restricted read-only audits confirmed retained accounting. Live provider quality, actual billing and real midnight crossover remain unproven. |
| N6 | Qualify isolated Nexus Python/Node build, independent verification, cancellation/recovery and ARM64. | Coordinator with release-gap specialist | N0, accepted job contract | Active | The committed source and five build wheels are verified; 13 candidate test wheels passed metadata review, an offline hash-enforced install and the fixed 12-case backend test. Node/image inputs, a new action, native execution and ARM64 remain unqualified. |
| N7 | Connect an accepted Nexus goal to cited strategy and a bounded management plan. | Strategy specialist | N2, N3 | Backlog | Preserve mandate, current evidence, approvals and lifetime caps. |
| N8 | Produce evidence-linked presentation and internal support drafts for the same Nexus goal. | Presentation/support specialist | N7 and actual accepted evidence | Backlog | Components exist; Nexus-owned integrated outputs remain unproven. |
| N9 | Show whole-cycle costs/outcomes and qualify owner notification and delivery reconciliation. | Reporting specialist | N3, N7, N8; notification configuration | Backlog | Offline pieces are not live email-delivery evidence. |
| N10 | Prepare and qualify private deployment, independent restore, rollback and 24-hour soak. | Operations/security specialist | N4, N5, N6, N9; applicable service authority | Backlog | Preserve existing Pi services; follow the Pi and product risk/validation skills. |
| N11 | Independently assess auth, spend, ownership, recovery and full supervised release evidence. | Milestone reviewer | N2, N3, N4, N5, N6, N7, N8, N9, N10 for final acceptance | Backlog | Review concrete milestones; missing/failed checks remain open. |

## Current coordination evidence

- Feature checkpoint `361c562` was committed and pushed to
  `origin/feat/company-foundation`; the remote ref was read back at the same
  commit. This is a development checkpoint, not a PR or release. Its 80%
  coverage gate, owner acceptance, native builder and other release gates remain
  open. The four designated unowned files stayed outside the commit.
- On 29 October, a narrow legacy Alembic Ruff baseline was added without
  changing published migrations. Its guard verifies the 16 revision hashes and
  exact unsuppressed historical diagnostics, including source spans; CI runs
  both broad Ruff and that guard. Six focused guard tests passed. A prior test
  launch failed at pytest setup because the async plugin was omitted, and the
  first negative-test draft failed because an inline noqa was itself flagged;
  both failures were retained and the corrected checks passed. The literal
  full strict mypy command passed on 1,803 source files with named exceptions for
  absent optional legacy SDKs, whose APIs remain unqualified. An unrelated
  missing-import probe still failed as intended. The broader worktree Ruff run
  additionally finds seven issues in the two preserved unowned Python files;
  broad Ruff plus the guard passed on the candidate excluding those files.
- Candidate `dfa660a2…5bc3` includes the current lint and CI changes. All
  5,828 unit tests passed in 26 serial slices without skips; its backend bytes
  match the prior snapshot that passed literal strict mypy and guarded broad
  Ruff. CI-targeted format checking also passed. This run does not provide new
  coverage. Receipt: `/var/tmp/nexus-v8-full-unit-20261029-1/aggregate.json`.
- A clean HEAD-based projection of the model transport/estimator checkpoint
  passed 204 focused tests. Its whole-backend Ruff check found four long lines
  and its format check identified three test files; those files were formatted
  afterward and need a fresh projection/check. Full strict mypy was OOM-killed
  in its 1 GiB scope, so its result is incomplete; the scope is empty and
  failed. Retain the output in
  `/var/tmp/nexus-transport-projection-plan-20261029-1/static-run/` and do not
  repeat the unchanged full command without a revised resource plan. These
  checks were on a projection, not a committed feature checkpoint.
- A fresh projection with the three reformatted tests then passed all 204
  focused tests plus full-backend Ruff lint and format checks. A reduced mypy
  run that skipped imports reported 11 Any-related errors; full-project typing
  remains incomplete, and the next scoped attempt must retain real types.
  Receipts: `/var/tmp/nexus-transport-projection-plan-20261029-2/run/focused-runner-receipt.json`
  and `/var/tmp/nexus-transport-projection-plan-20261029-2/static-run/receipt.json`.
- All six changed production modules subsequently passed strict mypy with normal
  imports, individually and serially in bounded scopes. This is scoped typing,
  not the required full-project check; the five-module run sampled a peak of
  1,053,196,288 bytes under its 1 GiB limit and recorded no OOM. Receipts:
  `/var/tmp/nexus-normal-import-mypy-20261029-1/output/receipt.json` and
  `/var/tmp/nexus-normal-import-mypy-remaining-20261029-1/output/receipt.json`.
- A separate compatibility probe on that projection ran 41 tests across the
  older planning, evidence-owner and coding-worker modules: all passed, no
  skips, source drift or OOM, with its scope inactive. This does not replace
  a complete unit or coverage run. Receipt:
  `/var/tmp/nexus-projection-compat-20261029-1/receipt.json`.
- The exact projected unit suite collected 5,607 cases in 25 serial slices.
  Slices 1–21 passed; slice 22 failed one test because an older fixture used a
  UTC date instead of the Bangkok billing date. Its scope stopped cleanly; the
  final three slices were not run. The already-existing worktree fixture repair
  and its deterministic midnight regression must enter a new projection before
  revalidation. Failed receipt and plan:
  `/var/tmp/nexus-projection-full-unit-20261029-1/PLAN.json`.
- Full-project strict mypy completed on the v2 projection under a revised
  1.5 GiB cap without OOM, but failed with 86 errors: missing optional
  integration packages and errors concentrated in new transport test typing.
  It is not a pass; see
  `/var/tmp/nexus-full-strict-mypy-20261029-1/output/mypy-full-strict.log`.
- A fresh v3 projection included the corrected Bangkok fixture, its existing
  deterministic boundary test and typed transport tests. It passed 358 focused
  tests and whole-backend Ruff/format; a normal-import focused mypy run found
  one incorrect test annotation. That annotation was fixed afterward and needs
  a fresh source and checks. Full-unit and full-project typing remain open.
  Receipts: `/var/tmp/nexus-projection-v3-draft-20261029-1/validation/`.
- The subsequent v4b projection corrected that one annotation and passed 358
  focused tests, full-backend Ruff/format, and strict normal-import mypy on both
  typed test modules. All three owned scopes stopped. Receipts:
  `/var/tmp/nexus-projection-v4b-draft-20261029-1/validation/`.
- The same v4b projection then passed all 5,609 collected unit cases in 25
  serial slices, with no failures or skips; all owned scopes retired and the
  1,873-file source inventory and hashes remained exact. JUnit verification
  compares function/parameter counts rather than unstable individual UUID
  parameter IDs. No coverage was collected on this projection; the 80% gate and
  full-project typing remain open. Plan and slice receipts:
  `/var/tmp/nexus-v4b-full-unit-20261029-1/aggregate.json`.
- A later reconciled test candidate freezes 1,900 files: the prior v9 source,
  five updated tests, three N5 tests, CI configuration and the tracked
  architecture document. It excludes the four unowned files and retains the
  historical one-shot A6 files, which are not portable acceptance tests. This
  is source preparation only; it has no same-source full-unit or coverage result
  and does not contain the full frontend or an owner-preview Git fixture.
  Receipt: `/var/tmp/nexus-reconciled-v9-20261029-1/freeze-receipt.json`.
- A fresh unit coverage chain on that candidate collected 5,822 cases in 26
  whole-module slices from empty coverage. Slices 1–15 passed 3,496 cases;
  slice 16 failed one SDK close-ownership test after a mock ModelAPIError and
  timed-out wait. The scope stopped without OOM; its cause is under diagnosis.
  Later slices and the coverage threshold report were not run. Preserve the
  failed slice and data: `/var/tmp/nexus-candidate-unitcov-20261029-1/slice-016.log`.
- An instrumented isolated reproduction reached SDK transport roughly 5.4 s
  after starting with a one-second mock endpoint deadline; the stop/expiry guard
  denied that late handoff before the mocked POST. Instrumentation can alter
  timing and does not establish the original slice's precise cause. The success-
  path test now opts into a longer test-only setup window while retaining its
  close barrier and cancellation assertions; fresh-source checks are pending.
  Diagnostic: `/var/tmp/nexus-sdk-close-diagnostic-20261029-2/output/trace.json`.
- On a new 1,900-file candidate differing only in that test fixture, the
  formerly failing close-ownership test passed under coverage; its Ruff,
  formatting and strict normal-import mypy checks passed. A full coverage chain
  on this repaired source is still required; the failed prior chain is not reused.
  Receipts: `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/nexus-sdk-close-focused-20261029-1/`.
- A separate repaired-source coverage chain has freshly collected 5,822 cases
  and started 26 serial slices from empty coverage. Slice 1 passed; slice 2
  failed one coding-preparation case with a synthetic worker-identity time
  denial. The failing case took 0.281 s, not the full slice's 3m42s; a fixed
  mock clock captured before credential issuance can precede its integer-second
  issued-at time, but the failed log did not record both timestamps. Its exact
  cause remains a hypothesis. No later slices or threshold report ran; the owned
  scope stopped. Evidence: `/var/tmp/nexus-candidate-unitcov-20261029-2/slice-002.log`.
- A controlled synthetic diagnostic then showed that a captured clock just
  before a newly issued credential's next-second timestamp is denied before
  claim, while a clock sampled when awaited after issuance reaches the claim.
  The original failure did not retain timestamps, so its exact cause is still
  unproven. The positive test now samples its mock clock when awaited; no
  production credential, clock or deadline changed. Fresh validation is pending.
  Diagnostic: `/var/tmp/nexus-clock-iat-diagnostic-20261029-1/output/trace.json`.
- The corrected test and all six neighboring coding-preparation tests passed
  under coverage on a new frozen candidate; scoped Ruff, format and strict
  normal-import mypy also passed. The new full coverage chain remains pending.
  Receipt directory: `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/nexus-coding-clock-focused-20261029-2/`.
- A new exact-source coverage chain has collected 5,822 cases into 26 slices,
  prioritizing both repaired modules first. All 26 passed with no skips. The
  unchanged unit-only 80% coverage report failed: 85,553 / 133,736 statements,
  63.971556%; 21,436 additional statements would be needed at this denominator.
  No same-source integration coverage is included. Report and receipts:
  `/var/tmp/nexus-candidate-unitcov-20261029-3/coverage-gate.json`.
- Both reusable N5 scenarios then passed with coverage on that same frozen
  source and separate private PG17 clusters; their independent audits and scope
  cleanup passed. The exploratory combined report covered 86,313 / 133,736
  statements (64.539840%), adding 760 statements and still failing 80%; 20,676
  additional unique statements are needed at this denominator. A separate
  per-file comparison found no baseline measured files or lines lost. The unit
  run did not fully pin dependency bytes, so cross-run runtime identity remains
  a qualification limit. Report:
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n5-integrated-coverage-20261029-1/coverage-gate.json`.
- On that candidate, CI-targeted Ruff lint and formatting passed. The broader
  required `ruff check .` failed with 83 diagnostics in historical Alembic
  files; these migrations were not altered. Full CI-style mypy found two type
  errors in the historical coding transport test helper. A test-only typed
  lookup repair is now in the working tree and needs fresh validation. The
  literal unsuppressed mypy check also remains open due to missing optional
  integration packages. Logs:
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n4-candidate-static-20261029-1/`.
- The type-only helper repair was independently reviewed as preserving dynamic
  lookups and patch/restore behavior. A new frozen 1,900-file snapshot exists,
  but its focused tests and typing have not run. Sustained workstation I/O
  pressure held the next test; the Pi was reachable with about 12 GiB available
  and 69 GiB root space, but its Python 3.13 environment and effective test caps
  do not yet qualify the pinned Python 3.12 workload. No Pi service changed.
  Next packet: `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/nexus-transport-typing-focused-20261029-1/REVIEW.md`.
- Full-backend mypy passed for 1,781 source files on v4b with strict mode and
  the CI `--ignore-missing-imports` flag, with no OOM or source drift. This used
  the existing local interpreter rather than CI's frozen uv environment and
  does not satisfy the literal unsuppressed full strict check: six optional
  integration distributions are absent. Receipt:
  `/var/tmp/nexus-v4b-full-mypy-ci-20261029-1/output/receipt.json`.
- The missing integration SDKs are not in the current Nexus dependency lock.
  Metadata for two sampled legacy Langfuse releases shows conflicts with pinned
  `packaging` or `httpx`; this is not proof that every candidate is incompatible.
  Resolve and verify any separate development dependency set before using it
  to rerun the literal unsuppressed mypy check. A resolver packet is prepared
  but unexecuted; its whole-executor request boundary is not yet established.
- Two authenticated Brain API mounting/search cases passed against an owned,
  disposable PostgreSQL 17 cluster. The original v9 coverage data stayed
  unchanged; the candidate copy gained 311 covered statements, reaching
  85,854 / 133,352 (64.381487%). The 80% gate still fails, with 20,828
  additional statements needed at the same denominator. Source membership and
  hashes were stable, no OOM occurred, and the owned database and scope stopped.
  Runtime dependency bytes were not fully pinned across the two runs. Receipt:
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/brain-app-coverage-v9-draft-1/supervisor-terminal.json`.
- Orca runtime `1.4.205` was started on 28 October. Supervised run
  `run_1199955e8aaf` is bound to a newly created Nexus coordinator terminal;
  the Orca-managed launch workspace is historical `/mnt/data/company/ai/Nexus`,
  while the sole implementation checkout is `/mnt/data/nexus-sdd-2026-10-05`.
- First N0 and N1 worker-start attempts stopped at an interactive Codex update
  prompt before task delivery. Both exact task-owned terminals were released
  through their Orca receipts; neither worker performed its task. Investigate
  a supported startup correction before retrying either attempt.
- A later N0 retry on an operator-created terminal was accepted by Orca, but
  its actual agent turn is **unconfirmed** after workspace and hook prompts.
  Dispatch `ctx_d3f542e6b445` remains live/ownership unresolved; do not resend
  the task or launch another editor from an observation timeout. A separate
  Waypoint candidate never reached an Orca-confirmed idle state and was closed
  without dispatch. The accepted N0 input also selected the linked Nexus Git
  root's workspace trust prompt; hook definitions were explicitly left untrusted.
  The unintended exact trust stanza was subsequently removed and all other
  parsed configuration preserved; whether the already-running session reloaded
  that change is unverified. The worker dispatch remains unconfirmed.
- An earlier empty run was inadvertently bound to an unrelated existing
  terminal. It has no workers or tasks; do not send to or reset that terminal.
- Earlier `/var/tmp` evidence is historical where no longer available. Do not
  recreate a lost receipt or claim its contents were freshly verified.
- Nine current workflow/auth source files match the recorded historical hashes;
  this is not a complete source-cohort reconciliation. Four selected current
  workflow-identity cases passed in 26.75s with mocked sessions; they do not
  launch DBOS or connect PostgreSQL.
- A fresh, isolated PG17/DBOS3.2 metadata probe used production `_enqueue_exact`
  and separate actual planning/coding no-op workers. Both namespaced versions
  registered and their commands reached SUCCESS; the legacy-v1 command remained
  ENQUEUED without an executor, and a fresh enqueue of that old identity was
  denied and rolled back. All 886 frozen Python source pins stayed unchanged;
  both child exits and owned PostgreSQL shutdown were confirmed. The 1 CPU /
  1 GiB / zero-swap / 128-PID scope is inactive and disposable DB data removed.
  Receipt: `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/nexus-version-probe.json`.
  This is metadata compatibility only, not an actual model or company cycle.
- A new private cache fetch for the original `3fda71b` source timed out after
  30 seconds before producing an archive or receipt. Its owned process scope is
  inactive and the partial private cache is retained. The source filesystem is
  fuseblk and the private destination is ext4; the cause of the delay is unknown.
  Record: `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/source-recovery-failure.json`.
  Do not rerun the unchanged fetch or revive any old issued action.
- A changed preparation using a private bare repository with an explicit
  alternate to the original local Git object store passed. Its archive SHA256
  matches the historical `a30ca35a…`; both selected committed source files were
  accepted by the actual CodingRepositoryReader, and a wrong archive hash was
  denied. The new receipt's typed `SourceReceipt` shape also validates. This
  cache depends on the original object store; it is not an independent backup.
  New receipt: `/home/santapong/.codex/nexus-source-recovery-20261028-2/SOURCE_SELECTION_20261028.json`.
- A new 1,890-file backend source cohort was frozen and hash-checked against the
  live checkout; two unowned probes and environment files were excluded. Its A6
  scenario collects successfully. The v9 source changes only fresh namespace and
  receipt literals relative to the preserved v8 fixtures; AST comparison passed.
  Manifest: `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/nexus-cohort.json`.
  The actual v9 SDK-mock workflow then failed after planner dispatch: the
  planner returned `outcome_unknown`, with `sdk_resources_unresolved` and no
  observed mock HTTP POST. Its restricted-role SELECT-only metadata audit rolled back and found
  one unknown synthetic hold of USD0.004164, held consistently in work and daily
  ledgers, no lease or other app connection. The actual child was reaped, source
  pins stayed unchanged and the owned PostgreSQL cluster is stopped. Data and
  logs remain under `/var/tmp/nexus-coding-application-actual-checks-20261028-9`
  and `/var/tmp/nexus-coding-application-pytest-20261028-9`. No coder or live
  provider request occurred; do not refund, reset or retry this issued action.
- A fresh v10 diagnostic fixture adds timing-only SDK-context, pre-SDK and
  mock-transport markers without request content or credentials. The v9 failure
  is not sufficient to identify which protected step exceeded the deadline.
  The original two-second synthetic endpoint timeout, worker, wire assertions,
  policy checks and other acceptance assertions remain unchanged. Ruff and
  format checks pass on the three touched integration files; scoped monkeypatch
  setup/restoration passes without network access. A new 1,890-file source
  snapshot holds the previous cohort plus exactly those three fixture forwards.
  V10 completed as a failure after the planner's one mock POST and before a
  coder POST. Its trace shows the coder's pre-SDK check ran about 3.77 seconds,
  exceeding that fixture's 2-second endpoint timeout; the actual outcome and
  hold remain unknown. A separate restricted-role SELECT-only audit rolled back with
  planner USD0.000002 reconciled, coder USD0.010507 unknown/held, matching daily
  and work budgets, no leases or other app connections. Owned workers and PG
  stopped; all source pins stayed unchanged. Keep both v9 and v10 results.
  Neither v9 nor v10 recorded actual transaction isolation or read-only mode;
  those server-enforced properties are unverified for these two audits.
- The mock transport was overriding the configured endpoint timeout to two
  seconds. A test-first regression reproduced that mismatch, then passed after
  the fixture retained the actual configured value instead. Explicit two- and
  30-second endpoint cases and the existing short-deadline/no-late-issuance test
  pass (3 checks). Production timeout/authority code is unchanged. A fresh v11
  namespace uses this changed test configuration. Its 1,891-file source cohort
  is frozen with only the three fixture forwards and one added test relative to
  v10; Ruff/format pass on those four files. The fresh v11 test passed in
  123.48s; it cannot erase the v9/v10 unknown holds.
  Its original wrapper failed to locate the configuration because pytest made
  a directory and a symlink to it; the test itself passed and the owned PG was
  stopped. A separate read-only restart of the same synthetic database then
  passed the independent conservation audit and stopped PG again. It confirmed
  two attempts, intents, dispatches and publication sources, no leases or other
  app connections, and USD0.000004 known mock spend. A durable evidence packet
  is `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/a6-v11-milestone/MILESTONE.json`.
  This proves SDK-mock application behavior only; live model quality, native
  execution, owner browser and whole supervised release remain open.
  Diagnostic record: `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/nexus-timeout-diagnosis.json`.
- The first planned 2,900-case coverage batch was interrupted deliberately after
  386.72 seconds because progress indicated it would exceed the fixed ten-minute
  phase budget. Pytest's retained JUnit contains 728 matching passed cases, no
  failed/skipped cases, and exit 2 for interruption. The owned scope is inactive;
  no coverage data was saved, so neither the batch nor the 80% gate passed. Its
  private log/XML/receipt are in `unit-regression/` under the learning directory.
- The new serial-slice plan accounts for all 5,797 collected cases and 435
  modules once; each completed slice must pass on the same source before its
  coverage data can be appended to the next. Plan:
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/unit-regression-v2/BATCH_PLAN.json`.
  Slices 1 and 2 passed all 299 assigned cases on the unchanged cohort, saved
  and appended coverage, and left no processes in their task scopes. Receipts
  `slice-01.json` and `slice-02.json` are in the same directory; no full-suite or
  global coverage result follows yet.
- Slice 3 stopped with 108 passes and one coding-worker failure: the expected
  historical candidate was `outcome_unknown` after a synthetic SDK mock POST.
  The source cohort remained unchanged; the scope is inactive, and the failed
  slice did not alter the saved coverage from slice 2. Preserve the unknown
  outcome while diagnosing it. `slice-03.json`, its JUnit and log are retained
  beside the earlier slice receipts.
- A fresh synthetic, metadata-only timing diagnostic passed on the unchanged
  cohort. Its endpoint budget was 1 second, less than the 14.29 seconds remaining
  on its SDK deadline; one mock POST completed with known billing. This proves
  the active limit in the fresh run, not the exact limit in the failed run. No
  coverage was written, source pins held, and its capped scope stopped without
  OOM. Receipt: `coding-timeout-diagnostic-1/receipt.json` under the learning
  directory. The original failure and unknown synthetic outcome remain preserved.
- A deliberately delayed 1.2-second mock response reproduced an unknown SDK
  outcome with the old one-second success fixture. The success test now opts in
  to a ten-second endpoint; the helper's one-second default and the worker's
  original operation/SDK limits stay unchanged. On a fresh 1,891-file cohort,
  both immediate and delayed success cases and the original short-deadline
  no-late-POST guard passed (3 checks); Ruff and formatting passed for the two
  changed test files. The exact cause of the original slice failure is still not
  known. Red/green receipts: `coding-timeout-red-1/receipt.json` and
  `coding-timeout-green-1/receipt.json` in the learning directory. New source
  means old coverage cannot be combined with the next full-suite result.
- The updated 1,891-file cohort matches the checkout and collected 5,798 unique
  tests across 435 modules. A new 27-slice plan assigns every collected test
  exactly once; coverage starts in a separate file and keeps the unchanged 80%
  gate. The first slice is running in its own capped scope. Plan and future
  receipts: `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/unit-regression-v3/`.
  The first eight slices passed all 1,714 cases with unchanged source and appended
  coverage; the third includes the repaired test. The
  host reserve did not fit the prior 1,280 MiB cap, so this phase uses a 768 MiB
  hard cap with zero swap; earlier sampled slice peaks were below 300 MiB. The
  monitor retains and reports any resource stop or OOM.
- Slice 9 stopped after 222 passes on
  `test_actual_sdk_single_post_and_recorded_file_readback[valid-openai]` with a
  preserved-provider/recorded-billing mismatch after a synthetic POST. The scope
  stopped with no OOM and source pins held; coverage remains at the slice-8 hash.
  A fresh delayed-response test reproduced the error; a test-only repair makes
  the fake recorder preserve unknown billing. All 20 planning-consumer tests,
  including both providers' unknown/no-candidate/no-second-POST cases, and Ruff
  passed. The original failure's exact slow step is unknown. Receipt, JUnit and
  log are in `unit-regression-v3`; focused red/green logs are in the learning
  directory's `planning-consumer-red-1` and `planning-consumer-green-1`.
  These changes require a new coverage cohort and leave v3 coverage separate.
- The fresh v4 cohort matches the checkout and collected 5,800 unique cases.
  Its 27-slice plan runs the two repaired areas first and then the remaining
  modules exactly once. The first slice passed all 242 cases. The second stopped
  at 12 passes and one timeout in a fresh post-cancellation origin read; source
  pins held, no OOM occurred and prior coverage was unchanged. Diagnose before
  retrying or altering the finite original deadline.
- A first fresh origin diagnostic failed before the target because temporary
  directories were not private; that staging error is retained. A new private
  run passed with the original 10-second read and 20-second lease, drained the
  cancelled read's owners and finished the second read with 5.25 seconds left.
  It did not use coverage and did not establish the original timeout's cause.
  A focused same-source coverage diagnostic subsequently passed; neither the
  original failed slice nor the full suite is reclassified as passed.
- The focused coverage diagnostic passed with the original deadline, but had
  only 1.05 seconds of read headroom. A separately recorded full-slice retry
  was stopped by the resource monitor after sustained host CPU pressure; it
  had no completed JUnit result, made no coverage change and left no scope
  processes. Both outcomes are retained; the cause of the original failure
  remains unknown. Retry receipt: `slice-02-retry-1.json` in `unit-regression-v4`.
- After renewed CPU admission, a second same-source retry passed all 239 cases
  and appended coverage to the verified slice-1 data. Subsequent slices require
  `slice-02-retry-2.json` explicitly; the original failure and interrupted retry
  are not overwritten. V4 slices 3–9 subsequently passed 1,475 more cases;
  V4 has 1,956 passing cases so far, not a full-suite pass.
- V4 slice 10 stopped with 51 passes and one failure in the OpenAI SDK-mock
  conformance case, where the model result was `failed` instead of `response`.
  Source pins held, no OOM occurred and the earlier coverage hash was unchanged.
  Diagnose the returned status and actual boundary before retrying. Receipt and
  log: `slice-10.json` and `slice-10.log` in `unit-regression-v4`.
- A fresh coverage-instrumented diagnostic returned unknown
  `sdk_resources_unresolved` and observed one synthetic mock POST about 6 ms
  after the adapter returned; the owned SDK task then settled. The original
  failure lacks equivalent timing, so its cause is not proven. The ordering and
  effect boundary are under independent review before any timeout adjustment or
  suite retry. Diagnostic evidence is under `provider-conformance-diagnostic-v4-1`.
- Independent source review established that the SDK request had already begun
  before the stop latch, but the trace did not capture when HTTP transport was
  entered. Existing tests cover a stopped pre-SDK gate, not suspension inside
  the SDK before transport delegation. A deterministic synthetic boundary check
  is being prepared. Do not claim the observed handler timestamp proves a new
  transport dispatch after stop; an already-delegated request cannot be recalled.
- A deterministic separate offline test then paused the actual pinned SDK path
  immediately before HTTP transport delegation, waited for timeout and released
  it. Both provider cases delegated to MockTransport after the unknown return;
  two pre-SDK and two already-delegated controls passed. The owner requested an
  action harness with current authority at the effect boundary, so a transport
  delegation guard is being implemented for not-yet-delegated calls. Already
  handed-off operations cannot be recalled and retain unknown accounting. These
  synthetic tests do not establish live provider or ledger behavior.
- A six-file candidate adds a per-attempt guarded handoff to the normal and
  qualification SDK paths and updates qualification source pins, retaining the
  exact legacy set for historical decoding. Handoff commitment and stop are
  ordered by a short lock; once committed, the async delegate can still advance
  and must be treated as potentially issued. Independent source review informed
  the pin and test updates. The 1,893-file candidate cohort is frozen; focused
  focused checks first ran 129 passed / one failed: the short-deadline fixture
  was denied before its intended claim boundary. The test-only correction sets
  one finite deadline before admission and uses events to confirm claim and
  pre-SDK entry. A fresh 1,893-file cohort then passed all 130 focused checks,
  including both mock providers, qualification pins and SDK ownership. Manifest
  `/var/tmp/nexus-provider-boundary-cohort-20261028-3/manifest.json` SHA256
  `cce9c27b7ec3072f8da9b61baee70d52de3f291c5c5f885a20df3344e7d9e756`;
  receipts/JUnit are `focused-2-*` and `focused-3-*` in the review packet.
  Earlier v4 coverage does not apply to the changed production source. Fresh
  integrated workflow and full coverage are being prepared. An isolated v12
  application/audit packet is prepared on the new source; its separately
  reviewed failure snapshot configures and checks read-only transaction settings and
  preserves uncertain results. Its harmless scope/cleanup rehearsal failed
  before either case: the pinned Python 3.12 lacks `os.pidfd_open` and
  `signal.pidfd_send_signal`. The exact driver scope was later inactive/dead
  with no control group, and sibling scopes were never started. No PostgreSQL
  was started. Fix and qualify the runtime-specific process control first.
- The runtime-specific pidfd probe subsequently passed with two owned synthetic
  children; the real scoped timeout/SIGKILL rehearsal passed with sentinel and
  cleanup evidence. Fresh v12-estimator PG17/DBOS/SDK-mock execution then failed
  during coding preparation (503) after successful planning. A separate scoped
  repeatable-read/read-only rollback snapshot recorded one reconciled planning
  hold (USD0.000002), no coder intent/hold and no live lease. PostgreSQL and the
  owned scope stopped, with no OOM or source mismatch. Retain this failed run;
  do not replay any issued action. Evidence in
  `/var/tmp/nexus-coding-application-actual-checks-20261028-12-estimator/` and
  `a6-v12-estimator-prepared-2/` under the learning directory.
- A separately supervised follow-up restarted only that retained synthetic
  cluster and verified a repeatable-read/read-only rollback snapshot for the
  exact coder Work. It was blocked, with no coder journal action, attempt,
  intent or hold. The cluster and scope stopped without OOM. This narrows the
  failure state but does not identify the 503 cause. Restart can alter PG's
  internal WAL/control files; no action was replayed or reset. Evidence:
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/v12-coding-journal-audit-prepared-1/audit.json`.
- Fresh v13 used a new synthetic company/DB/action namespace and timing-only
  fixture. It passed the actual owner planning→coding→publication test in
  110.08 seconds with two SDK MockTransport requests. The same-run restricted
  repeatable-read/read-only audit passed and rolled back, confirming two
  succeeded intents/attempts/dispatches, both publication records, reconciled
  synthetic USD0.000004 and no live leases. All 1,894 source pins stayed stable;
  the owned PostgreSQL and scope stopped without OOM. During its controlled
  coding preparation the Git archive took about 4.85 seconds and the intended
  interruption was reached with time remaining. This does not determine v12's
  503 cause, prove real-provider quality, or complete native execution. Evidence:
  `/var/tmp/nexus-coding-application-actual-checks-20261028-13-timing/` and
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/a6-v13-timing-prepared-1/`.
- A libc-backed pidfd compatibility helper was prepared and source-reviewed;
  the first independent synthetic probe never started because its scope identity
  handshake timed out. The exact scope is now inactive/empty and no PostgreSQL
  or probe child was started. The failed receipt remains in
  `a6-v12-pidfd-prepared-2/`; a separate predicate-level identity diagnostic is
  being prepared before any retry. A new full-coverage plan is also being
  prepared for the changed, focused-tested production source. Predicate-level
  diagnostic identified that the scope launcher and worker were the same PID;
  their start ticks, cgroup, invocation, membership and limits matched. The
  failed probe had incorrectly required the worker to be its own child. The
  diagnostic scope stopped; the old failure remains retained.
- Fresh 1,893-file source collected 5,818 unique unit cases in 436 modules.
  Its separate v5 plan has 27 slices and keeps the 80% gate; the first two slices
  passed 274 tests with instrumented coverage. Slice 3 failed immediately because
  the input estimator still pins the pre-guard adapter source. The correct
  fail-closed source pin has since been requalified by a static framing comparison
  and a new v2 recipe pinning both adapter and guard. A fresh cohort passed 204
  focused checks, including legacy proof denial; new integrated and full coverage
  runs remain open. Do not reuse an old approval. Prior plan/receipts:
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/unit-regression-v5/`.
- The final estimator-and-transport source snapshot collected 5,822 unit cases
  and has its own 27-slice coverage plan. Its first six slices passed 1,182 cases,
  including the changed estimator and model boundaries. Slice 7 stopped after
  172 passes because a Google continuation case saw no initial mock POST; a
  fresh guard-handoff diagnostic found its one-second fixture deadline had
  expired before delegation. Response-focused fixtures now opt into a bounded
  10-second endpoint while short-boundary tests keep the default; 92 focused
  checks passed. The new test source requires another separate cohort. The full run and 80%
  report are still open; prior cohort coverage is separate. Evidence:
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/unit-regression-v6/`.
- The newest test-only fixture source is collected into a separate v7 plan:
  5,822 cases in 27 serial slices, with a strict 80% final gate. Slices 1–16
  passed 3,539 cases including changed-boundary/continuation cases; slice 17
  stopped after 53 passes and one ownership-test failure. Source, logs and coverage are in
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/unit-regression-v7/`.
- Slice 17's retained synthetic evidence records `sdk_resources_unresolved` with
  unknown billing and no mock POST. The file-thread stall started, but the test
  stopped before its ownership/no-release assertions. Its shared composition had
  a one-second SDK timeout; a narrow test-only setup correction is being checked
  without changing the original recording deadline or ownership assertions.
- The corrected recording-stall test and related suites passed 125 focused
  checks, including exact one POST and original cleanup/owner assertions. A fresh
  v8 cohort collected 5,822 tests and its first twelve slices passed 2,662. A
  mistyped slice-3 runner path exited before tests or a receipt; its scope stopped
  and coverage was unchanged. A corrected launch passed under a new scope.
  Plan and receipts: `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/unit-regression-v8/`.
- V8 ultimately passed slices 1–19, totaling 4,226 cases. Slice 20 stopped after
  13 passes because the backend-only cohort lacked `frontend/package.json`; it
  also requires `frontend/package-lock.json`. Both are tracked and match HEAD.
  A fresh coherent cohort will add these two exact inputs; v8 coverage is not
  combined with it. Static unit-test inventory found no other direct frontend
  or documentation reads, but dynamic dependencies remain possible.
- V9 freezes the 1,893 prior source files plus both exact tracked frontend
  metadata files (1,895 total), collected 5,822 tests and prepared 27 slices.
  All 27 slices passed 5,822 cases, including the previously missing-input case.
  Evidence: `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/unit-regression-v9/`.
- The actual unchanged `coverage report --fail-under=80` failed at
  64.148269% (85,543 of 133,352 statements); 21,139 additional covered
  statements are needed on that denominator. The configured `--cov=nexus`
  includes test code as well as product code. Missing statements include
  19,357 in integration tests, 8,063 in other test paths and 20,134 in product
  source. This is not release acceptance; select meaningful same-source
  integration checks without changing the threshold or padding coverage.
- The native collaboration runtime became available on 28 October. Two
  read-only specialists were dispatched: coding-worker failure diagnosis and
  release-gap review. Their findings await coordinator review. A third Waypoint
  review was interrupted to keep the initial active child count at two; this is
  distinct from the older, still-unconfirmed Orca dispatch above.
- The two native specialists completed their initial read-only reports. Their
  subsequent implementation/preparation turns failed at model capacity; the
  coordinator continued the focused fixture work. No work from those failed
  follow-up turns is counted as delivered.
- The N6 source inventory found all nine builder-required source paths match
  committed tree `ba832dbd95f19fca5cec083c1467074a2ae82729` at `1dcf415`, while
  two frontend scripts are absent from the earlier `3fda71b` selected source.
  The old v11 issued action cannot be rebound. Builder recipe and assets are
  untracked runtime inputs and need their own frozen hashes; a source selection
  alone does not qualify the image or authorize execution. Keep the existing
  two-file CodingRepositoryReader selection under its 65,536-byte total limit;
  validate the nine builder metadata rows separately against the same new
  committed source because `backend/uv.lock` alone exceeds that reader limit.
- Fresh source preparation now passes against `1dcf415` tree `ba832dbd…`:
  the unchanged archive guard accepted the 18,432,000-byte archive (2,386
  entries), the actual two-file reader passed and denied a wrong hash, and all
  nine separate builder rows matched the same archive and Git blobs. Receipt
  `/home/santapong/.codex/nexus-builder-source-20261028-1/SOURCE_SELECTION_20261028.json`
  has SHA256 `8fda76ee610d4ef929d1219abe8d40e1276cdb042d1c0cbef11ed5ebcc875fd2`.
  The capped scope stopped without OOM; the private alternate depends on the
  original object store. This is source preparation, not input-closure, image,
  native execution, owner approval or backup evidence.
- N6 limited inventory rechecked the exact prior build-wheel receipt, closure
  diagnostic and mixed-toolchain plan paths: all three are absent or not
  ordinary files; the fresh source receipt is present. Payload locations,
  test dependency closure, target base image and Node/Python toolchain remain
  unconfirmed—not necessarily absent. A bounded new input qualification is
  required before claiming an offline builder image or ARM64 execution.
- On 29 October, five source-pinned universal build wheels (234,287 bytes)
  were downloaded serially from the approved public host into a private output.
  The header-stripping hook first passed a synthetic redirect/cookie check; the
  scoped acquisition then independently rehashed all five saved files, checked
  sizes and exact output inventory, observed zero OOM events and stopped. This
  establishes only those build inputs, not the test dependency closure, Node
  tree, base image, native run or ARM64. Receipt:
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n6-five-wheel-acquisition-20261029-5/terminal.json`.
- A separately reviewed 13-wheel Linux x86_64/CPython 3.12 candidate matched the
  frozen lock and target markers; two wheels were reused from the build inputs.
  On 29 October the remaining 11 candidate wheels (4,473,972 bytes) were
  downloaded from the approved host and independently rehashed; the owned scope
  stopped without OOM. All 13 bytes are present, but wheel metadata and the
  actual offline test must still establish closure. Evidence:
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n6-eleven-wheel-acquisition-20261029-1/terminal.json`.
- A bounded metadata-only review then verified all 13 nominated wheel files,
  identities, selected platform tags, Requires-Python and active dependency
  requirements against the pinned candidate. No extraction or code execution
  occurred; the scope stopped without OOM. This supports the declared static
  graph only. The isolated offline install and fixed recipe test, target image,
  dynamic imports and ARM64 are still open. Receipt:
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n6-wheel-metadata-review-20261029-1/terminal.json`.
- A fresh CPython 3.12 x86_64 environment installed those 13 pinned wheels with
  offline/no-index/hash checks and no dependency expansion, then passed all 12
  fixed `test_company_management_plans.py` cases with the required plugins.
  The full extracted source tree matched the committed archive before and after;
  the owned environment was removed and scope stopped without OOM. This is a
  host test, not a qualified image, frontend build, native verifier or ARM64.
  Receipt: `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n6-offline-test-qualification-20261029-2/terminal.json`.
- A bounded amd64 npm metadata run selected 165 unique packages from the
  receipt-bound frontend lockfile, checked the six frontend inputs and actual
  Node/npm version metadata, and stopped its scope without OOM. The current
  parser selects both glibc and musl Rollup variants. This is a manifest, not an
  npm cache, installation, frontend build, image or ARM64 qualification.
  Receipt: `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n6-npm-manifest-20261029-1/terminal.json`.
- All 165 lockfile-pinned npm tarballs were acquired from the public registry in
  nine batches and independently verified against their SHA-512 integrity values:
  23,225,544 bytes total, no OOM and all owned scopes stopped. A real cold
  cache assembly read back all 165 inputs, and `npm ci --offline
  --ignore-scripts` installed 168 packages on committed `1dcf415`; all 19
  direct dependency versions matched the lock, source was unchanged, no OOM,
  scope stopped and owned scratch removed. Receipt:
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n6-npm-real-offline-ci-20261029-draft-1/terminal.json`.
  This host install alone does not establish the native verifier or ARM64.
- A fresh reconstruction of committed `1dcf415` repeated the offline npm install,
  then passed TypeScript and a Vite production build on amd64. The output HTML,
  JS, CSS and referenced assets were independently checked; source was unchanged,
  no OOM occurred, and owned scope and scratch stopped. Vite warned that the
  808.8 kB JS chunk exceeds its 500 kB advisory threshold. Browser acceptance,
  the actual Nexus native builder/verifier and ARM64 are not established.
  Receipt: `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n6-npm-frontend-build-20261029-draft-1/terminal.json`.
- The existing mixed Python/npm Nexus builder recipe still requires an immutable
  platform image, pinned dependency-tree hashes and a cold-image receipt before
  a real author/verifier pair. Public Docker Hub metadata identifies Python
  `3.12.9-slim-bookworm` as a candidate; image bytes, executable path, ABI,
  isolation and ARM64 remain unverified. The old Node image is for a different
  recipe. The prior v13 model-produced blank-line patch proves mechanics only;
  a meaningful Nexus release cycle needs a fresh approved product change.
- Committed `1dcf415` has 16,631,523 expanded source bytes against the fixed
  16,777,216-byte builder source ceiling, leaving 145,693 bytes. Any newer
  source commit must be measured from its exact archive before selection; an
  estimate of the current dirty tree is not an archive or authorization proof.
- A pre-commit staged-tree archive measurement found 17,166,542 expanded bytes,
  389,326 over that fixed ceiling. The measurement was taken before this board
  note, so the eventual commit's exact archive must be measured again. A reviewed
  private export policy may omit non-required documentation, but no such source
  selection or builder execution is qualified yet; do not omit required code,
  tests or lockfiles or widen the source bound to hide the mismatch.
  Receipts: `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n6-npm-batch-01-20261029-2/terminal.json`
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n6-npm-batch-02-20261029-1/terminal.json`,
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n6-npm-batch-03-20261029-1/terminal.json`,
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n6-npm-batch-04-20261029-1/terminal.json`,
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n6-npm-batch-05-20261029-1/terminal.json`,
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n6-npm-batch-06-20261029-1/terminal.json`,
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n6-npm-batch-07-20261029-1/terminal.json`,
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n6-npm-batch-08-20261029-1/terminal.json`,
  and `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n6-npm-batch-09-20261029-1/terminal.json`.
- A separate synthetic npm cache probe passed an offline installation from its
  private SRI-addressed cache; empty-cache and changed-SRI cases were denied.
  The install-script sentinel remained absent under `--ignore-scripts`, though
  no scripts-enabled positive control proves that flag alone caused it. The
  original probe failed before installation because user/global config used the
  same file; its evidence is retained. The revised environment was cleaned up.
  Receipt: `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n6-npm-synthetic-cache-20261029-2/terminal.json`.
- A Waypoint specialist reviewed the trial without browser access or writes.
  After explicit owner return, verify the signed-in Home view and acceptance
  evidence. Before migration, freeze the local board and re-list projects,
  reconcile existing Nexus records and preserve N0–N11-to-UUID identities; then
  create dependencies in order and read back every status, version and evidence.
  On conflicts re-read; on an uncertain create inspect fully and stop if the
  identity is ambiguous. The existing Waypoint seed script is specific to its
  own project and eight tasks and is not a qualified Nexus importer.
- The model-gateway specialist found existing separate restricted-PG checks for
  provider settlement/unknown/replay and synthetic cross-day reservation moves.
  A useful next check is a fresh isolated same-day two-provider cap/unknown
  scenario with actual issuance, zero-POST denial, immutable Work quotas and
  conserved holds. Use a separate Work for cap denial: an unresolved intent
  independently blocks a new call on the same Work. `EffectStore.begin` uses
  PostgreSQL's real clock; a true midnight crossing requires an actual bounded
  run at 00:00 Bangkok and cannot be inferred from a fixed-clock fixture.
  Preparation found the existing qualification and effect-budget fixtures use
  different company identities and policy versions. A faithful combined check
  needs fresh matching registrations and separate Work IDs; do not splice the
  fixtures or seed a budget row as though that proved real issuance. The proposed
  cap and unknown scenarios need separate disposable database namespaces.
  An independently reviewed, unexecuted v2 cap-case draft is at
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n5-cap-draft-2/test_nexus_n5_cap_draft.py`.
  It includes independent synthetic usage/cost assertions and is deliberately
  blocked before connecting. Effective network/host-socket isolation, complete
  restricted-role audit, owned database teardown and execution evidence remain
  open. A local user/network namespace creation probe passed; it does not prove
  the full isolation boundary. A scoped bwrap probe passed using only owned
  synthetic sockets: its private socket worked, the hidden synthetic Unix socket
  and host-side loopback listener were unreachable, and listener threads stopped.
  Receipt: `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n5-bwrap-probe-2/result.json`.
  The in-process cgroup controls were verified; the monitor missed the
  short-lived cgroup, so its peak and independently observed process count are
  unknown. Proportionality review found the user's offline N5 test does not
  require bwrap or a new staging framework. Prepare a fresh v11-style Unix-only
  PG/clean-environment/actual SDK MockTransport runner with restricted-role
  audit and owned teardown; preserve the gated draft. Hard process egress
  isolation, live providers and production qualification remain unproven. The
  revised runner and audit are in `n5-cap-v11-style-4/` under the learning
  directory; independent static review found no unsafe destructive operation in
  the intended flow. A real harmless scope/timeout/SIGKILL rehearsal and the
  actual database test remain unexecuted, and scope membership is unverified.
- A later read-only review found that this older N5 packet predates the current
  transport guard, uses unavailable Python pidfd APIs and cannot verify the
  intended audit transaction mode as written. Do not launch it. A fresh v4b
  source-bound packet needs the exercised pidfd/scope controls and an audit
  configured read-only and repeatable-read before its first query. The cap case
  denies its third request before issuance; it does not exercise unknown billing,
  which requires a separate fresh scenario.
- The replacement v4b cap-only test passed in an isolated PG17 cluster: two
  known SDK MockTransport calls reconciled synthetic usage, a separate Work
  recorded a synthetic overbill, and the next held request was denied with no
  third POST. The independent restricted audit verified repeatable-read,
  read-only mode, explicit rollback and recorded conservation; source pins
  remained unchanged, no OOM occurred, and PG and scope stopped. This is not
  real provider billing, unknown-result recovery or a midnight crossing.
  Receipt: `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n5-cap-v4b-20261029-1/supervisor-terminal.json`.
- A separate fresh v4b PG17 scenario issued one Google SDK MockTransport POST
  with missing usage, retained the unknown synthetic hold and durable attempt,
  and denied replay without a second POST. A restricted repeatable-read,
  read-only rollback audit confirmed retained accounting and lease release;
  source remained unchanged, no OOM occurred and owned PG/scope stopped. This
  does not establish live provider billing or quality. Receipt:
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n5-unknown-v4b-20261029-1/supervisor-terminal.json`.
- The two behaviors have now been translated into reusable repository
  integration tests with separate explicit disposable-database URLs. Source
  review prompted stronger attempt identity assertions. Each new test passed
  against its own fresh PG17 cluster on a frozen v4b-plus-tests source; separate
  restricted read-only audits confirmed conservation and both owned scopes
  stopped without OOM. After correcting a type-only fixture import, both tests
  passed again on the updated frozen source; Ruff, formatting and strict mypy
  with normal imports passed on the three test files. Latest receipts:
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n5-reusable-cap-20261029-2/supervisor-terminal.json`,
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n5-reusable-unknown-20261029-2/supervisor-terminal.json`,
  and `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/n5-reusable-static-20261029-2/`.
  Separate PostgreSQL CI matrix rows now select each test and its own database;
  workflow structure and shell syntax were checked locally. Remote CI and its
  PostgreSQL 16 service have not been exercised by the local PG17 runs.
- At 14:35 Bangkok on 28 October, the Pi was reachable with about 12 GiB
  available, 68 GiB free root space, 56.5°C and tailnet-only Serve/Funnel;
  core health probes passed. Its shared test-lane observer showed another run
  `cve-20261028-round2` reserved. The host reports ARM64/Python 3.13, while this
  Nexus check is pinned to Python 3.12/PostgreSQL 17; compatibility and an
  isolated runtime have not been qualified. No Pi test was started or lane
  modified. Older resume/RuView probes returned no response and were not
  diagnosed as part of Nexus work.
- Waypoint's two existing synthetic seed cases pass (`2 passed in 0.45s`): a
  lost committed response is resolved by a fresh read, while an unresolved
  write stops without a duplicate POST. Local record:
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/seed-uncertain-create.json`.
  This does not prove live HTTP, PostgreSQL, browser or migration behavior.
- A separate disposable PostgreSQL 17 and real ASGI test client passed 10
  existing project/task, optimistic conflict, dependency and acceptance cases.
  Private frozen source pins remained unchanged; the exact owned database was
  stopped and removed. Effective aggregate limits were 1 CPU, 768 MiB RAM,
  zero swap and 128 PIDs. The 4.7-second run ended before the first five-second
  resource sample, so no sampled peak is claimed. Receipt:
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/pg-trial-result.json`.
  One dependency deprecation warning was recorded. PostgreSQL 17 is not the
  native Pi PostgreSQL 16 deployment; owner-view and migration checks remain.
- Two further isolated ASGI/PostgreSQL17 cases exercised the existing Waypoint
  seed operator with an actual committed task write whose response was lost,
  and an unresolved write before commit. The first produced eight distinct saved
  records from eight POSTs; the second stopped after one attempt. Both passed and the
  owned test database was stopped and removed. Receipt:
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/pg-uncertain-result.json`.
  This covers the Waypoint seed operator in a fixture, not a Nexus importer or
  production-network failure. One dependency deprecation warning was recorded.
  A fresh run with an explicit returned-ID assertion also passed both cases:
  `/home/santapong/.codex/learning/nexus-waypoint-20261028-1/pg-uncertain-result-2.json`.

## Authority and preservation

Use plain Git, never `gh`. Preserve all existing uncommitted work and the four
unowned files identified in the Nexus checkpoint. No reset, broad staging or
cleanup. Existing feature-branch push authorization does not authorize a merge,
release tag or deployment. Do not access credentials, passwords or invitation
contents. External messaging, provider spending and Pi service changes remain
subject to their actual authorization. An uncertain effect or billing hold is
not a success, failure, refund or automatic retry.
