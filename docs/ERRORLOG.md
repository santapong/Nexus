# ERRORLOG.md
## NEXUS — Error & Bug Tracking Log

> **Update this file whenever you find a bug, silent failure, wrong assumption,
> or unexpected behavior — even if you fix it immediately.**
>
> The purpose is to build a knowledge base so future agents and humans
> do not repeat the same mistakes.
>
> Format defined in AGENTS.md §10.
> Most recent entry at the top.

---

## Severity Reference

| Severity | Meaning |
|----------|---------|
| `critical` | Data loss, security issue, or silent incorrect behavior that corrupts state |
| `high` | Incorrect behavior that affects task outcomes or agent memory |
| `medium` | Incorrect behavior that degrades quality but doesn't corrupt state |
| `low` | Minor issue, cosmetic bug, or suboptimal but not wrong behavior |

## Status Reference

| Status | Meaning |
|--------|---------|
| `open` | Error discovered, fix not yet implemented |
| `fixed` | Root cause addressed, verified by test |
| `mitigated` | Partially addressed, full fix deferred to BACKLOG |
| `wont-fix` | Known issue, accepted risk, documented reason |

---

## Error Entry Template

Copy this template for each new error.

```markdown
## ERROR-{NNN} — {short description}

**Date:** YYYY-MM-DD
**Severity:** critical | high | medium | low
**Status:** open | fixed | mitigated | wont-fix
**Found by:** {agent_name or 'human'} during {task or context}
**Affected files:** {list}

### What happened
{Exact description of the incorrect behavior. Be specific.
Include: what was expected vs what actually happened.}

### Root cause
{Why did it happen? Wrong assumption? Missing guard? Race condition?
Missing test? Bad default? Dependency behavior?}

### Fix applied
{What was changed to fix it?
Include: commit hash or PR number if available.
If status is 'open': describe what fix is needed and who should do it.}

### Prevention
{What prevents this from happening again?
- New test name + location
- New rule added to AGENTS.md or CLAUDE.md (section number)
- New guard or validation added
- Dependency version pinned}

---
```

---

## Error Log

<!-- New entries go here, below this line, newest first -->

## ERROR-056 — Offline answer extraction overstated conditional and co-occurring dates

**Date:** 2026-10-14
**Severity:** medium
**Status:** fixed
**Found by:** independent alternate-source probes of the test-only baseline
**Affected files:** `tests/brain_answer_fields.py`, baseline/observer and alternate-source tests

### What happened
Rejected or undecided deadline/supersession language became asserted facts.
Two dates in one primary source collapsed to the first; broadening collection
then mistook a report event date for an explicitly unknown deadline.

### Root cause
First-match/co-occurrence regex rules lacked syntactic binding and uncertainty
handling. Source access alone does not prove the extracted assertion is true.

### Fix applied
Support explicit affirmative bound deadline clauses only. Negated, conditional,
unknown or disjunctive unsupported language stays unknown; repeated supported
contradictory deadlines remain unresolved. Current derivative conflicts are
captured with truthful changed/historical metadata rather than omitted.

### Prevention
Four unchanged independent probes pass after failing before the corrections;
alternate-value/negative/unknown/evaluator19 checks pass1.55s. Scorer/source/
questions/goldens remain unchanged. Second29/30 andall16critical is independently
recomputed; B06 remains visibly failed, first17/30 is preserved. This is not
production LLM or general natural-language truth qualification.

---

## ERROR-055 — Publication replay, candidate identity and invalidation used incomplete bindings

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed
**Found by:** replay_worker tests-first publication probes; independently reviewed
**Affected files:** `brain/claim_links.py`, `brain/ontology_support.py`, publication tests

### What happened
Same-ID replay could project caller endpoint references instead of stored ones.
A stored pass candidate could initially publish verified_by as a source report;
duplicate candidate UUIDs also lacked unambiguous native/action binding. Links
between distinct resources invalidated only the subject view.

### Root cause
Replay helpers trusted requested projections, candidate existence was confused
with trusted acceptance, and event emission omitted the second endpoint.

### Fix applied
Compare immutable stored endpoint IDs/kinds before replay. Require unambiguous
same-company candidate/action lookup; verified_by source-report promotion stays
disabled. Emit bounded ID-only events for both endpoint resources atomically.

### Prevention
Original failing probes and focused fixes are retained in the publication work
receipt. Final7unit+23restricted-PG checks pass30/98.88s with93%505statement
coverage. Independent review matched6source/8test/4log hashes and approved the
scoped foundation; this cannot substitute for the failed original answer gate.

---

## ERROR-054 — Current entity read hid superseded supporting sources

**Date:** 2026-10-14
**Severity:** medium
**Status:** fixed
**Found by:** independent M2 review using actual source R1→R2 ingestion
**Affected files:** `brain/api_services.py`, Brain API graph tests

### What happened
The current entity endpoint returned an R1-derived source-report after R2
withdrew its support, without a stale/history label.

### Root cause
It requested historical evidence internally and discarded the materialized
source-state/freshness classification.

### Fix applied
The current endpoint rejects historical or stale supporting material with a
revision conflict. Explicit historical evidence reads retain their labels.

### Prevention
The retained real-ingestion HTTP test observes200 before update,409 afterward
without the old label, and200 for the explicitly historical citation. Three
graph/expiry/staleness cases pass9.07s; independent original probe passes1case
5.25s separately before final combined acceptance.

---

## ERROR-053 — Large committed-Git reads truncated or hung during PIPE cleanup

**Date:** 2026-10-14
**Severity:** medium
**Status:** fixed
**Found by:** root's large-stream source-reader tests
**Affected files:** `company/brain/git_source.py`, its unit tests

### What happened
A single bounded stream read returned partial content; waiting for a terminated
child with unread PIPE output hung the original oversized-source test.

### Root cause
StreamReader.read(n) does not promise n bytes or EOF. Child exit and output drain
are separate lifecycle conditions.

### Fix applied
Drain to EOF with a strict byte cap and drain child output during kill cleanup.
Keep exact company/path/commit/blob/hash checks and argv-only Git execution.

### Prevention
Twelve source-reader cases pass, including multibyte and oversized PIPE output.
Actual nominated StockFlow five-blob ingestion also passes. Only the confirmed
task-owned hung test process was terminated; no shared service was changed.

---

## ERROR-052 — Time-only expiry crossed protected read and effect preparation

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed
**Found by:** independent combined M2 review with original restricted-PG probes
**Affected files:** `brain/api_services.py`, `harness/model_authorizer.py`,
`execution/effect_store.py`, Brain model/API regression tests

### What happened
An entity's separate grant expired during evidence checking. A legitimately
assembled source grant and an immutable exact approval could expire during
input estimation while the SDK request still issued.

### Root cause
CompanyControl prevents concurrent authority writes but cannot stop the clock.
Earlier timestamps/checks were reused after awaited preparation.

### Fix applied
Refresh entity-resource checks at the final read. Run the Brain check before and
after model input validation. Refresh database time, execute lease and exact or
standing authority after all preparatory hooks before effect mutation.

### Prevention
Original independent entity/source/approval probes now deny without disclosure
or wire issuance. Retained Brain gate30 checks pass, including both estimator
expiry cases with unchanged ledger; shared default model45 checks pass. Issued
effects remain recorded honestly; these gates cannot undo an external request.

---

## ERROR-051 — Brain composite PK ordering and nullable CHECK weakened schema assumptions

**Date:** 2026-10-14
**Severity:** medium
**Status:** fixed
**Found by:** root metadata tests and independent M2 restricted-SQL review
**Affected files:** `brain/model_base.py`, `brain/evidence_models.py`, normal
`company_008_brain.py`, metadata/schema guard tests

### What happened
Inherited company columns sorted after local identity columns. A parsed evidence
row with non-null parse/chunk IDs and null parsed offsets also passed SQL CHECK,
then failed typed read reconstruction.

### Root cause
ORM mixin declaration order did not guarantee the expected composite key order.
SQL CHECK accepts UNKNOWN; numeric bounds alone do not reject NULL.

### Fix applied
Explicit company-first mapped-column ordering; require both parsed offsets
IS NOT NULL in the parsed branch. Mirror the ORM in the unmerged normal008 DDL.

### Prevention
Metadata ordering tests, retained direct restricted-insert denial,13 combined
ACL/schema checks and fresh/repeat/all43-table metadata/downgrade proof pass.
Already-merged legacy and company001–007 migrations remain unchanged.

---

## ERROR-050 — Earlier same-day tool reservations bypassed current spend overages

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed
**Found by:** independent combined M1 reviewer, with real restricted PostgreSQL reproductions
**Affected files:** `journal_reservations.py`, reservation-day and effect-budget integration tests

### What happened

After an issued request truthfully settled above its reservation, shared spent4.95+held0.10 exceeded the5.00 daily cap, yet another preauthorized same-day tool received a fresh permit. Separate reproductions showed current own-work and ancestor partition overages below the daily limit also allowed fresh generic tool intents. No external request was issued by these probes.

### Root cause

The day-transfer helper returned early for a same-day hold. Current work/ancestor checks existed only in the model-specific hook, rather than at the generic model/tool effect boundary.

### Fix applied

Every fresh generic intent now checks current shared held+spent and current own/ancestor partitioned allowances under CompanyControl before attempts/intent mutate. A same-day hold is counted once; cross-midnight transfer still adds only its transferred amount. Actual recorded charges remain intact. Root tests failed before the fix; enqueue/day14 passes afterward. The reviewer rechecked daily/own/ancestor denial and worker outcome truth together:3 tests pass7.70s. Durable effect-boundary regressions are retained in `test_company_effect_budget.py`.

### Prevention

Exercise already-authorized actions after a truthful overbill, including generic tools and ancestor allocations. Fresh authorization must inspect current ledger state; an earlier quote or cached hold is not current spend permission.

---

## ERROR-049 — Caught post-call failure returned blocked while the ledger retained an unknown effect

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed
**Found by:** independent combined M1 reviewer in an actual registered DBOS workflow
**Affected files:** `company_worker.py`, worker support/helper and process acceptance

### What happened

A trusted observation hook raised ValueError after the offline model invocation. DBOS completed with WorkerResult blocked, while release correctly retained outcome_unknown work/effect/cost hold with one model attempt and no receipt. The result hid unresolved issued work; it did not repeat the call or refund its hold.

### Root cause

The exceptional result was constructed before finally.release classified the committed intent.

### Fix applied

Return the exceptional result only after release; unresolved issued work returns outcome_unknown. Actual process regression also proves cached restart causes no second call. The complete worker package passes56 checks, including10 PostgreSQL/DBOS process cases, compatible-version recovery and a pending approval that releases capacity before segment2 resumes with the same allowances. Independent probe passes after the fix.

### Prevention

Test returned result, actual persisted effect/work/billing state and released capacity together, with faults after actual invocation. SDK workflow success never implies known effect outcome or completed business work.

---

## ERROR-048 — Blocked worker result and inactive-work audit diverged from persisted/public state

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed
**Found by:** Codex integration reviewers and actual HTTP/worker acceptance
**Affected files:** company access/routes, execution runtime/release, company worker, company006

### What happened

The pure owner READ policy allowed inactive work but HTTP handlers rejected it again; the owner received403/404 for retained history. A stale-source worker returned blocked while its released row remained running. A corrupted false-owner actor role could claim/consume counters despite being denied at API/effect boundaries. Revoked actors also could not classify/reconcile their expired issued intent, leaving the original state unresolved.

### Root cause

Policy was duplicated at HTTP materialization; execution lacked blocked/principal ownership and an independent owner recording path.

### Fix applied

Use one shared fresh actor/owner read policy at materialization. Actual HTTP owner audit now succeeds while actor/mutation access stays denied. Persist blocked release, principal-bound leases, canonical role mapping and explicit current-owner reconcile-only methods with trusted evidence. Worker source-state failures retain blocked and clear ownership. Twelve owner/hook and27 runtime cases pass;16 actual API and7 current worker process cases pass. Known-receipt/unknown-billing cost-only continuation is being completed separately; no amount is invented.

### Prevention

Test the public HTTP path, database state and released capacity together. Audit idempotent lease-return shortcuts as well as write guards; a reactivated actor cannot borrow the owner's recording fence. Candidates and blocked workflow results never count as completed business work.

---

## ERROR-047 — Draft migration ordering and prepared DDL were not replay-safe

**Date:** 2026-10-13–14
**Severity:** high
**Status:** fixed
**Found by:** Codex during real profile replay
**Affected files:** draft company002/004 migrations and company-profile validation

### What happened

Asyncpg rejected several top-level function/trigger commands in one prepared op.execute. Alembic autogeneration across metadata emitted a referring authority table before the grant's new composite unique key; a concurrently running fixture failed with InvalidForeignKeyError. Downgrade order also needed reversing.

### Root cause

Driver statement semantics and cross-metadata DDL ordering cannot be inferred from generated source or metadata compilation.

### Fix applied

Execute each top-level function/trigger command separately and order the target unique key before its referring FK table. Drop the referring table first on downgrade. Actual full profile install/repeat/metadata/downgrade passes; company006 also has a populated old-lease test proving live drain refusal, fenced expired intent, preserved counters and held unknown cost. Production migration was not performed.

### Prevention

Review generated operations and replay them on real disposable PostgreSQL. Keep source/schema comparisons and populated transition tests; do not stamp around a failure.

---

## ERROR-046 — Initial queue primitive allowed spliced segments and old-day holds

**Date:** 2026-10-13–14
**Severity:** high
**Status:** fixed
**Found by:** independent Codex integration review
**Affected files:** company dispatch/queue, journal reservations, effect boundary

### What happened

A review probe changed only segment_id to create two DBOS workflows for one authorized action without a registered execution row. Another probe passed prior-day authority while the new day already held the full$5 allowance.

### Root cause

Trusted-caller prerequisites were documented but not enforced in the primitive. Enqueue identity and effect-day spending were checked at different boundaries.

### Fix applied

Persist immutable action→segment dispatch; enforce current run/workspace/version and next persistent segment before SQL enqueue. Transfer only unissued held allowance to actual Bangkok effect day under the same company lock, preserving lifetime work totals and retaining unknown/issued charges. Exact and standing source/hold/dispatch/queue commit together. Twelve real queue/day cases and independent review closure probes pass.

### Prevention

Future gateway composition must use the same transaction for new model quote/catalog/counter/intent checks. Existing queue IDs and cached permits are never reusable authority; real process-kill tests check uncertain outcomes separately from SDK replay.

---

## ERROR-045 — Litestar body decoding relaxed StrictBool

**Date:** 2026-10-13–14
**Severity:** high
**Status:** fixed
**Found by:** actual restricted-database HTTP tests
**Affected files:** company API payload contracts and tests

### What happened

Despite StrictBool unit contracts, Litestar2.24 decoded Pydantic bodies with strict=False and accepted approved='true'. This turned a string intent into a boolean at the actual authorization HTTP boundary.

### Root cause

Framework decoding can override a field's strict mode; direct model unit validation did not exercise the transport behavior.

### Fix applied

Before-validators require literal JSON booleans for approval/pause; extra identity/cap fields are rejected. Actual signed HTTP tests prove malformed bodies cannot save decisions or pause, while current-owner valid intents succeed. No global schema/decoder relaxation was added.

### Prevention

New approval/control APIs need actual transport tests for boolean/numeric/identity wire types. Do not infer public boundary behavior from Pydantic unit checks alone. Scoped lesson is stored in the Nexus skill.

---


## ERROR-044 — Legacy chaos tests patched removed module locations

**Date:** 2026-10-13
**Severity:** medium
**Status:** fixed
**Found by:** Codex during SDK release regression
**Affected files:** `backend/nexus/tests/chaos/test_chaos_scenarios.py`, `backend/nexus/core/kafka/producer.py`

### What happened

On both SDK1 and SDK2 the legacy chaos suite had six failures and two teardown/setup errors. Redis mocks referenced the removed flat module paths; an async session-factory test incorrectly returned a coroutine rather than an async context manager. Unclosed Kafka producer warnings also surfaced after legacy tests contacted the real client.

### Root cause

Tests had not followed the earlier core-package restructuring. AsyncMock was unsuitable for a synchronous session factory. The producer startup path allocated a client, then failed without stopping it.

### Fix applied

Update the patch targets to the actual core modules and use a synchronous factory mock. These changes preserve assertions and do not widen runtime permissions. Close unsuccessful/cancelled producer startup clients while preserving the original exception; three new tests failed before that correction. The final targeted producer plus complete behavior/chaos regression passes 61 cases. The baseline original-SDK failure log is retained in the implementation evidence folder.

### Prevention

Run behavior/chaos tests during milestone integration; mock the namespace where a dependency is resolved. Passing unit tests alone is insufficient release regression evidence.

---

## ERROR-043 — Weak company JWT configuration reached signature verification

**Date:** 2026-10-13
**Severity:** high
**Status:** fixed
**Found by:** Codex during authenticated company-profile preflight
**Affected files:** `backend/nexus/api/company_auth.py`, `test_company_auth.py`

### What happened

The unmounted company helper rejected empty/unsigned configuration but accepted a short or known development key. Three new negative cases failed before implementation, including PyJWT's short-key warning.

### Root cause

Configuration checks only tested nonempty key and algorithm != none.

### Fix applied

The supervised pilot requires explicit HS256 configuration and a key of at least 32 characters, excluding the known development secret, in every environment. The complete company-auth unit package now passes 38 cases. No actual signer or credential was changed.

### Prevention

Use the same configuration validator at company-profile startup. Asymmetric signing requires a separate deliberately implemented key/issuer policy; it is not silently selected through the legacy settings field.

---

## ERROR-042 — Legacy RLS setters used invalid parameterized SET LOCAL

**Date:** 2026-10-13
**Severity:** high
**Status:** fixed
**Found by:** Codex multi-agent team during real PostgreSQL preflight
**Affected files:** `backend/nexus/api/middleware.py`, `backend/nexus/db/rls.py`

### What happened

The first real PostgreSQL test run had 9 failures and 2 passes. Prepared SET LOCAL statements failed with a syntax error. The request-session hook swallowed its failure, leaving an aborted transaction available to downstream code.

### Root cause

PostgreSQL SET syntax does not accept the prepared expression used here; catching all failures hid the binding error.

### Fix applied

Both paths bind values through SELECT set_config(..., true). The hook logs the error type and re-raises. Eleven real PostgreSQL cases now pass, including commit/rollback reset on the same pooled backend, SQL-shaped strings as values and fault propagation. This does not establish correctness of every legacy RLS policy.

### Prevention

Use test_company_rls_context.py against an explicit disposable PostgreSQL database. A mocked SQL session cannot prove prepared-statement syntax or connection-pool scope isolation.

---

## ERROR-041 — SDK 2 usage and legacy QA paths could silently report success

**Date:** 2026-10-13
**Severity:** high
**Status:** fixed
**Found by:** Codex multi-agent team during pinned SDK migration
**Affected files:** `backend/nexus/core/llm/run_usage.py`, agents, benchmarking, `verification/legacy_qa.py`, Temporal review activity

### What happened

SDK2 exposes RunUsage through a property and input/output token fields; old callable/request/response access could fall back to zero. Legacy QA accepted malformed or missing review fields, while the Temporal activity approved timeouts/errors. Negative usage/QA tests demonstrated these failures before implementation.

### Root cause

Best-effort extraction/default approval treated unavailable evidence as a successful result.

### Fix applied

Typed extraction supports the checked SDK interfaces and raises on unknown usage. Callers propagate that failure. Strict review parsing requires an unambiguous explicit boolean approval; missing/error/timeout/malformed reviews fail or request owner input while preserving raw evidence. 82 targeted cases pass on each SDK version; 59 QA/usage regressions pass. These are legacy review-contract checks, not independent company verification or live provider billing conformance.

### Prevention

Keep explicit API-family construction and version-pinned compatibility tests. Provider-payload missing-usage semantics still require adapter conformance before paid company routing; SDK-default zero alone is not billing proof.

---

## ERROR-040 — Existing legacy migration chain cannot replay on clean PostgreSQL

**Date:** 2026-10-13
**Severity:** high
**Status:** mitigated
**Found by:** Codex during clean company-profile migration preflight
**Affected files:** historical `backend/alembic/versions/003_*`, `006_*` and the legacy installation path

### What happened

Normal alembic upgrade head on a clean PostgreSQL17 database applied 001/002, then failed in 003: eval_results.task_id VARCHAR(36) references tasks.id UUID. Source inspection also found mismatched UUID references and policies referencing nonexistent columns in 006. The full legacy chain was not repaired or proven.

### Root cause

Historical migrations contain inconsistent foreign-key types and policy column references. Passing current metadata/unit checks did not prove replay of their DDL history.

### Fix applied

Preserve already-merged migrations001–016. ADR-101 introduces a separate company migration lineage/version table with explicit UUID-correct baseline. Its clean install/repeat/metadata/downgrade tests preserve an unrelated legacy data/version marker. This unblocks new company installations; the legacy replay issue remains unresolved for existing legacy operators.

### Prevention

Run actual migration replay against disposable PostgreSQL before release, compare ORM metadata with installed schema, and distinguish fresh company installation from legacy migration repair. Never hide a failed historical chain with create_all plus stamp.

---


## ERROR-039 — Typed monetary defaults were not validated in foundation models

**Date:** 2026-10-13
**Severity:** medium
**Status:** fixed
**Found by:** Codex during executable company-contract acceptance
**Affected files:** `backend/nexus/company/contracts/base.py`, `company.py`, `work.py`

### What happened

The first foundation test run returned the string `"5.00"` from a Decimal-annotated mandate default and raised serializer warnings for a string work-budget default. Three contract tests failed. A field annotation did not establish that the constructor's default value had been validated.

### Root cause

Pydantic default validation was not enabled, and string defaults had been assigned to Decimal fields. Type-ignore annotations concealed the static mismatch in the prototype.

### Fix applied

Use real Decimal defaults and enable default validation on the shared strict Contract. Remove the type ignores. The final 275-unit-test run and 59-case focused suite pass, including money bounds, wire roundtrips and the default mandate cap. No production data was affected.

### Prevention

Keep defaults type-correct and test runtime value/serialization, not just schema annotations. See [foundation validation](company-system/VALIDATION_2026-10-13.md). This is a scoped Pydantic default-value finding, not a claim that all typed models or other libraries behave the same way.

---

## ERROR-038 — Company runtime integration gaps at July HEAD

**Date:** 2026-10-05 (recorded); bounded probes executed 2026-10-04\
**Severity:** high\
**Status:** open\
**Found by:** Codex during the Nexus architecture review\
**Affected files:** `backend/nexus/tools/adapter.py`, `tools/guards.py`, `tools/workspace.py`, `agents/engineer.py`, `agents/base.py`, `core/kafka/consumer.py`, `integrations/temporal/task_workflow.py`, `integrations/temporal/activities.py` (all under `backend/nexus/`)

### What happened

At `6a8c8ef`, the locked unit/static suite passes but the operating boundary remains incomplete:

- No production caller binds `set_tool_context`; an actual irreversible file-tool probe raises `ToolContextUnsetError` without creating a file.
- Actual approval functions with a mocked DB flush and poll without a prior commit; a separate PostgreSQL-session visibility failure is inferred and still requires a live test.
- The installed Temporal SDK rejects `AgentTaskWorkflow` because it lacks workflow metadata. No live Temporal server was used.
- Actual Engineer prompt assembly includes an attachment sentinel but omits the workspace-file sentinel; semantic memory is outside normal context loading.
- Source inspection shows Kafka auto-commit/early seen-marker crash risk, optional Temporal QA approval on timeout/error, and `tool_workspace_write` directly persisting without its documented approval gate. These scenarios were not executed against live services.

### Root cause

Existing local tests do not establish cross-session approval, full runtime context delivery, registered durable execution or policy coverage across all mutation entry points. Transport markers and fallback defaults cannot establish verified business completion. The exact live consequences require integration acceptance rather than extrapolation from mocks.

### Fix applied

None. The documentation-only company redesign records remediation in [M1](company-system/IMPLEMENTATION_PLAN.md#m1--prove-one-governed-durable-execution-path), [M2](company-system/IMPLEMENTATION_PLAN.md#m2--build-the-evidence-backed-company-brain), and BACKLOG-069–070. Existing historical fixes in ERROR-027/036 are preserved; this entry describes current integration gaps at the reviewed July source, not a claim that all old fixes were absent.

### Prevention

Require real two-session approval tests, actual prompt/context tests, workflow registration/replay tests, all-entry-point mutation policy tests, crash/effect reconciliation and fail-closed verification. Raw bounded evidence: `/mnt/data/nexus-review-2026-10-04/architecture-probes.json` and companion logs. [SDD §4](sdd/NEXUS_SDD_v0.2.md#4-baseline-assessment-and-validation-limits) states their scope. Keep this error open until the corresponding runtime gates actually pass.

---

## ERROR-037 — Director loop-prevention false positives on empty meeting rounds

**Date:** 2026-05-19
**Severity:** medium
**Status:** fixed
**Found by:** audit war room (F7)
**Affected files:** `backend/nexus/agents/director.py`, `backend/nexus/core/kafka/meeting.py`

### What happened
Director's convergence/loop detection used `difflib.SequenceMatcher().ratio()` on round
transcripts. Empty strings (or rounds where all agents abstained) compared against each other
returned `1.0` (100% similarity), which the loop detector interpreted as a stagnation loop and
forcibly terminated the meeting before any real work landed.

### Root cause
`SequenceMatcher("", "").ratio()` is defined as `1.0` (both empty). The Director never guarded
against zero-length round content. Additional bugs found: `_similarity()` divided by zero on
single-agent meetings; `_count_unique_ideas()` deduplicated case-sensitively, treating "Idea"
and "idea" as different.

### Fix applied
- PR #39 (F7): explicit empty-string guard returning `0.0`; minimum two non-empty rounds before
  loop detection runs; case-folded idea deduplication; div-by-zero guard.

### Prevention
- Behavior tests added for empty/single-round meeting transcripts
- Director synthesis is integration-tested against a fixture of 50 historical meetings

---

## ERROR-036 — Plugin tools bypassed `require_approval()` for irreversible actions

**Date:** 2026-05-19
**Severity:** critical
**Status:** fixed
**Found by:** audit war room (F10)
**Affected files:** `backend/nexus/integrations/plugins/registry.py`

### What happened
`PluginTool` declared `requires_approval: bool` in its manifest but the runtime invocation path
never consulted that flag. A plugin could declare itself irreversible (e.g., `delete_repo`)
and still be invoked by an agent without any `human_approvals` record. This punched a hole
straight through Risk 4 / CLAUDE.md §20 NEVER rule 1 — for plugins only.

### Root cause
`PluginTool.__call__` invoked the registered handler directly. The original Phase 5 Track C
implementation forgot to call `require_approval()` on the same code path as `tools/adapter.py`
does for built-in irreversible tools.

### Fix applied
- PR #33 (F10): `PluginTool` now wraps every invocation in `require_approval()` when
  `manifest.requires_approval is True`, creating a `human_approvals` row and suspending the
  task until resolution. Identical semantics to `tool_file_write` etc.

### Prevention
- Unit test asserts `human_approvals` row exists before plugin handler runs
- Plugin registration validation rejects manifests with `requires_approval=True` and a
  handler that doesn't accept the approval context

---

## ERROR-035 — Billing endpoints leak cross-workspace data + Stripe replay possible

**Date:** 2026-05-19
**Severity:** critical
**Status:** fixed
**Found by:** audit war room (F8)
**Affected files:** `backend/nexus/api/billing.py`, `backend/nexus/integrations/stripe/service.py`

### What happened
1. `GET /api/billing/records` and `/api/billing/summary` queried `billing_records` without a
   `workspace_id` filter. Any authenticated user could see every tenant's billing.
2. Stripe `PaymentIntent` creation did not send an `Idempotency-Key` header, so a retried
   POST could double-charge a customer.
3. Audit COUNT for billing operations was wrong (used `len()` of a paged result instead of
   a SQL COUNT), under-reporting volume in the dashboard.

### Root cause
Phase 4 billing endpoints predated multi-tenant RLS. After Phase 5 RLS landed, the policy
covered most tables but the billing endpoints bypassed the session-scoped `workspace_id`
because they used a service-role session for "admin operations." That backdoor was never
narrowed.

### Fix applied
- PR #30 (F8): every billing query now joins on `workspace_id` from JWT; Stripe service helper
  `with_idempotency_key()` wraps `payment_intents.create` and `checkout.sessions.create`;
  audit COUNT uses `SELECT COUNT(*)`.

### Prevention
- E2E test: tenant A cannot see tenant B's billing records
- Replay test: same `Idempotency-Key` returns the original PaymentIntent, never a second one
- Linter rule: any direct `stripe.*.create()` call without `idempotency_key=` fails CI

---

## ERROR-034 — Audit log table unbounded and not append-only

**Date:** 2026-05-19
**Severity:** high
**Status:** fixed
**Found by:** audit war room (F11)
**Affected files:** `backend/alembic/versions/015_audit_log_partitioning.py`,
`backend/nexus/audit/service.py`

### What happened
`audit_log` was a single Postgres table growing unboundedly (millions of rows by Phase 7).
Query latency on the audit dashboard degraded to seconds. Worse, `UPDATE` and `DELETE` on
`audit_log` were not blocked at the DB level — a compromised admin role could rewrite history.

### Root cause
CLAUDE.md §12 declares the audit log "Immutable — never updated, never deleted" but that was
only enforced in application code. No DB-level constraint or partitioning existed.

### Fix applied
- PR #37 (F11) migration 015:
  - Converted `audit_log` to PARTITION BY RANGE on `created_at`, one partition per day
  - Added `BEFORE UPDATE OR DELETE` trigger that raises an exception on any non-INSERT
  - Backfilled retention policy: hot 30 days, cold partitions exportable to S3

### Prevention
- Migration adds the trigger so future schema migrations cannot silently relax it
- Audit-log retention test asserts UPDATE/DELETE raise `feature_not_supported`

---

## ERROR-033 — Kafka `task.results` consumer not idempotent + no signature validation

**Date:** 2026-05-19
**Severity:** critical
**Status:** fixed
**Found by:** audit war room (F3)
**Affected files:** `backend/nexus/core/kafka/result_consumer.py`,
`backend/nexus/core/kafka/signing.py`

### What happened
The `task.results` consumer processed every message it received without checking an
idempotency key. Because Kafka delivers at-least-once, a single task could be marked
"completed" twice, double-credited in billing, and double-broadcast to the WebSocket. Equally
serious: messages had a HMAC signature field (per Phase 7 enterprise security) but the
consumer never validated it.

### Root cause
The Phase 7 HMAC-signing module was added to the producer but the result consumer was missed
in the rollout — only the agent-response consumer was updated. Idempotency keys were similarly
applied to `agent.responses` but not `task.results`.

### Fix applied
- PR #31 (F3): result consumer now (1) verifies HMAC signature before deserializing payload,
  (2) writes `idempotency:result:{message_id}` into Redis db:3 with 24h TTL, skipping
  duplicates. Both behaviors match the `agent.responses` consumer.

### Prevention
- Chaos test resends the same `task.results` message 10× and asserts a single DB update
- New CI lint rule: every consumer class must override `validate_signature()` or explicitly
  opt out with a justification comment

---

## ERROR-032 — AgentBase invariants violated (heartbeat GC'd, memory-fail not DLQ'd)

**Date:** 2026-05-19
**Severity:** high
**Status:** fixed
**Found by:** audit war room (F4)
**Affected files:** `backend/nexus/agents/base.py`

### What happened
Three related AgentBase invariants from CLAUDE.md §7 were violated in production:
1. `_heartbeat_loop()` was launched as a bare `asyncio.create_task(...)` without holding the
   task reference. Python's GC could (and occasionally did) cancel the heartbeat mid-task,
   making the agent appear silent.
2. When `_write_memory()` raised, the result was published to `agent.responses` anyway — in
   direct violation of CLAUDE.md §20 MUST rule 2 ("Write episodic memory before publishing
   result").
3. Cleanup (`_release_lock()`, `_clear_working_memory()`) was inside `try` but not `finally`,
   so exceptions during `handle_task()` leaked locks.

### Root cause
The original AgentBase guard chain was written before mypy --strict was enforced. The fire-
and-forget heartbeat slipped past review. The memory-fail-publish bug was masked because
the test suite mocked memory writes to always succeed.

### Fix applied
- PR #36 (F4):
  - `self._heartbeat_task = asyncio.create_task(...)` — reference held on `self`
  - Memory write failures now route the message to `{topic}.dead_letter` instead of
    `agent.responses`
  - All cleanup moved into `finally` block

### Prevention
- New behavior test: simulate `_write_memory()` raising, assert result on DLQ, not on
  `agent.responses`
- Heartbeat reference is asserted non-None in `run()`

---

## ERROR-031 — Recovery service double-runs orphan tasks; circuit breaker race

**Date:** 2026-05-19
**Severity:** high
**Status:** fixed
**Found by:** audit war room (F12)
**Affected files:** `backend/nexus/core/recovery.py`, `backend/nexus/core/llm/circuit_breaker.py`

### What happened
1. `RecoveryService.scan_orphans()` re-queued orphan tasks (status=running, no heartbeat) but
   did not lock during scan. Two backend pods starting simultaneously both re-queued the same
   orphans → duplicate Kafka commands → tasks counted twice in billing.
2. `CircuitBreaker.record_failure()` and `record_success()` used separate `incr` / `set` calls
   in Redis, racing each other. A burst of mixed results could leave the breaker stuck in a
   wrong state.

### Root cause
Recovery scan didn't use a Redis lock. Circuit breaker mutations were not atomic.

### Fix applied
- PR #32 (F12):
  - Recovery scan acquires `recovery:scan_lock` (Redis db:3, 60s TTL) before re-queueing;
    second pod skips with a log line.
  - Circuit breaker state transitions now run as a single Lua script in Redis (atomic
    `EVAL` of read+update).

### Prevention
- Chaos test starts 5 backend pods simultaneously, asserts each orphan re-queued exactly once
- Circuit breaker stress test fires 1000 mixed success/failure events, asserts terminal state
  matches the analytical expectation

---

## ERROR-030 — A2A bearer tokens stored as plain SHA-256 (offline crackable)

**Date:** 2026-05-19
**Severity:** high
**Status:** fixed
**Found by:** audit war room (F9)
**Affected files:** `backend/nexus/integrations/a2a/auth.py`,
`backend/alembic/versions/014_a2a_pbkdf2_tokens.py`

### What happened
A2A bearer tokens were stored with a single round of SHA-256 (per ERROR-021's fix). An
attacker who exfiltrated the `a2a_tokens` table could brute-force tokens offline at billions
of hashes per second on a single GPU.

### Root cause
SHA-256 is a fast hash, designed for integrity, not password storage. The Phase 3 fix
correctly stopped storing plaintext but used the wrong primitive.

### Fix applied
- PR #34 (F9) migration 014: `token_hash` column now stores PBKDF2-HMAC-SHA256 with 480,000
  iterations and a per-token random 32-byte salt. Validation iterates only on lookup, which
  is fine because the dev token cache (5 min TTL) means hot tokens skip the KDF.

### Prevention
- Benchmark in CI: PBKDF2 verification ≥ 50ms, < 500ms (rules out tuning regressions)
- Documented in DECISIONS.md (new ADR): never use SHA-256 alone for any user-supplied
  credential storage

---

## ERROR-029 — OAuth provider secrets stored unencrypted; login lacked rate limit

**Date:** 2026-05-19
**Severity:** critical
**Status:** fixed
**Found by:** audit war room (F1)
**Affected files:** `backend/nexus/api/oauth.py`, `backend/nexus/api/auth.py`,
`backend/alembic/versions/013_oauth_encryption.py`

### What happened
1. Per-workspace OAuth client secrets (Google/GitHub/Microsoft) were stored in
   `workspace_oauth_configs.client_secret` as plaintext.
2. The login endpoint had no rate limit. A credential-stuffing attack could try thousands of
   passwords per minute against a single account.
3. RLS policies on workspace-scoped tables were vulnerable to a SQL injection vector through
   a partner integration query that concatenated `workspace_id` into a raw SQL fragment.

### Root cause
OAuth was added in Phase 5 Track A under time pressure; the encryption-at-rest design was
deferred and forgotten. The login endpoint inherited rate limiting from the general API
middleware but was explicitly exempted by an old TODO. The RLS injection vector existed
because one developer had bypassed the parameterized-query rule for "performance."

### Fix applied
- PR #38 (F1) migration 013: `client_secret` column encrypted with AES-GCM keyed by an
  application secret (separate from JWT secret). Decryption only at OAuth flow time.
- Login endpoint: per-IP and per-email sliding-window rate limit (5 attempts / 15 min).
- RLS policies hardened: the offending query rewritten using SQLAlchemy expression-language
  with bound parameters.

### Prevention
- CI scanner blocks any commit adding `f"...{user_input}..."` inside a `text()` SQL call
- Security checklist now requires "secrets at rest are encrypted, not just hashed"

---

## ERROR-028 — Missing DB indexes cause N+1 latency in analytics endpoints

**Date:** 2026-05-19
**Severity:** medium
**Status:** fixed
**Found by:** audit war room (F5)
**Affected files:** `backend/alembic/versions/012_missing_indexes.py`,
`backend/nexus/api/analytics.py`

### What happened
After Phase 5 the analytics endpoints showed acceptable latency, but a load test with 100k
tasks blew P95 query times to 4+ seconds. The culprits were missing composite/partial
indexes — Risk 19 had been marked RESOLVED but only the highest-traffic paths were covered
in migration 005.

### Root cause
Migration 005 indexed the well-known hot paths but missed several composite indexes that
only matter at higher cardinality:
- `(workspace_id, status, created_at DESC)` on `tasks`
- `(agent_id, created_at DESC) WHERE outcome='failed'` on `episodic_memory`
- `(provider, created_at DESC)` on `llm_usage` partial index
- `(workspace_id, resolved_at)` on `human_approvals` partial index WHERE status='pending'

### Fix applied
- PR #29 (F5) migration 012: adds the four indexes above plus three more identified by
  `pg_stat_statements` review.

### Prevention
- Every new endpoint must include an `EXPLAIN ANALYZE` snippet in the PR description proving
  no seq scan on tables > 10k rows
- Quarterly `pg_stat_statements` review added to ops checklist

---

## ERROR-027 — Tool `require_approval()` not enforced for built-in irreversible tools

**Date:** 2026-05-19
**Severity:** critical
**Status:** fixed
**Found by:** audit war room (F2)
**Affected files:** `backend/nexus/tools/adapter.py`,
`backend/nexus/tools/guards.py`, `backend/nexus/core/sanitization.py`

### What happened
The `require_approval()` guard had existed since Phase 0 (Risk 4) and was referenced in every
irreversible tool wrapper in `tools/adapter.py`. But the actual call site had drifted: several
tools (`tool_send_email`, `tool_git_push`, `tool_hire_external_agent`) had been refactored
through a code-generation pass that dropped the `await require_approval(...)` line. The
`human_approvals` record was created — but as a *log-only* row, with no blocking semantics.
Agents could send emails or push code without waiting for human approval.

Additionally, agent outputs published to `agent.responses` contained raw PII (emails, phone
numbers extracted from web search) that the dashboard would render. There was no sanitization
between LLM output and Kafka publish.

### Root cause
Code-generation for the multi-modal tool refactor reformatted the irreversible tool wrappers
and the human reviewer didn't notice the missing `await`. The PII sanitization gap was a
known §23 follow-up that never landed.

### Fix applied
- PR #40 (F2): re-added `await require_approval(...)` on every irreversible tool in
  `tools/adapter.py`. Added a unit test that monkey-patches `require_approval` to track calls
  and fails if any of the 3 irreversible tools fires without invoking it.
- New `core/sanitization.py.sanitize_output()` runs PII redaction (emails, phone, SSN, credit
  cards, API keys) on every agent response before Kafka publish. Reversible via task_id for
  audit replay by an authorized admin.

### Prevention
- Behavior test in `tests/behavior/test_irreversible_tools.py` asserts that an agent
  attempting `send_email` without an approved `HumanApproval` row raises `ApprovalRequired`
  and the email is NOT sent
- CI rule: any new `tool_*` function in `adapter.py` flagged as irreversible must contain
  a literal `await require_approval(` in its body

---

## ERROR-026 — Embeddings never generated; vector recall returns NULL

**Date:** 2026-05-19
**Severity:** high
**Status:** open — PR #35 (F6) closed without merging on 2026-05-19
**Found by:** audit war room (F6)
**Affected files:** `backend/nexus/memory/episodic.py`, `backend/nexus/memory/semantic.py`,
`backend/nexus/memory/embeddings.py`

### What happened
Every row written to `episodic_memory` and `semantic_memory` since Phase 1 has `embedding =
NULL`. The semantic-recall query from CLAUDE.md §12 (`ORDER BY embedding <=> $query`) sorts
NULLs last in cosine-distance ordering, so it consistently returns zero matches. Agents start
every task with cold context — none of the "agents learn from past tasks" promise is
operational at the recall path.

### Root cause
`nexus/memory/embeddings.py` defines `generate(text: str) -> list[float]` but no caller ever
invokes it. The original CLAUDE.md §12 design specified a Taskiq fire-and-forget job
triggered on every memory write; that wiring was deferred during Phase 1 ("we'll add it once
agents have output to embed") and forgotten.

### Fix needed
1. Add a Taskiq task `taskiq_embed_episode(episode_id)` that loads the row, calls
   `embeddings.generate()`, writes the result back to `embedding`, updates the `ivfflat` index.
2. Call it from `EpisodicMemory.write_episode()` and `SemanticMemory.upsert()` as
   `await broker.kicker().with_labels(low_priority=True).kiq(...)`.
3. One-off Alembic migration script to backfill embeddings for the existing ~120k rows in
   batches of 100, paced to stay under the Google embedding-001 RPM limit.

PR #35 attempted this but was closed without merging on 2026-05-19. A follow-up PR is
required to ship the fix. Tracked as BACKLOG-052.

### Prevention
- E2E test that writes an episode, sleeps for the fire-and-forget worker, queries semantic
  recall, and asserts at least one result
- Migration assertion that the `episodic_embedding_idx` row count > 0 in every non-empty
  deployment

---

## ERROR-025 — Missing authorization on approval resolution endpoint

**Date:** 2026-03-18
**Severity:** high
**Status:** open
**Found by:** claude_code during security audit
**Affected files:** `backend/nexus/api/approvals.py`

### What happened
The `POST /api/approvals/{id}/resolve` endpoint accepts `resolved_by` as a user-controlled
string in the request body. No JWT validation or authentication check is performed. Any
caller can approve or reject human approval gates by spoofing the `resolved_by` field.

### Root cause
The approval endpoint was built in Phase 0 before the auth system existed (Phase 4). When
JWT auth was added, this endpoint was not updated to extract identity from the token.

### Fix needed
1. Extract `resolved_by` from JWT token (authenticated user email/id), not from request body
2. Reject unauthenticated requests with 401
3. Log the actual authenticated user in audit trail

### Prevention
- All state-changing endpoints must validate JWT and extract identity from token
- Add integration test: approval without valid JWT returns 401

---

## ERROR-024 — Unsafe workspace slug generation allows collisions

**Date:** 2026-03-18
**Severity:** high
**Status:** open
**Found by:** claude_code during security audit
**Affected files:** `backend/nexus/api/workspaces.py`

### What happened
Workspace slugs are generated from email prefix: `data.email.split("@")[0].lower().replace(".", "-")`.
No validation regex, no uniqueness check, no UNIQUE constraint on the slug column.
Multiple users with the same email prefix (e.g., `john@gmail.com`, `john@company.com`)
would get the same slug, causing conflicts.

### Root cause
Slug generation was implemented as a quick v1 approach without considering multi-tenant
collision scenarios.

### Fix needed
1. Add slug validation: `^[a-z0-9\-]{3,50}$`
2. Add UNIQUE constraint on `workspaces.slug` column via Alembic migration
3. Handle collision: append numeric suffix if slug already exists
4. Reject invalid slugs at API boundary

### Prevention
- Alembic migration for UNIQUE constraint
- Unit test for slug collision handling

---

## ERROR-023 — Missing tenant isolation on task creation and listing

**Date:** 2026-03-18
**Severity:** high
**Status:** open
**Found by:** claude_code during security audit
**Affected files:** `backend/nexus/api/tasks.py`

### What happened
`POST /api/tasks` creates tasks without setting `workspace_id`. `GET /api/tasks` lists
all tasks without filtering by workspace. In a multi-tenant system, users from one
workspace can see tasks from all other workspaces.

### Root cause
Task API was built in Phase 1 (single-tenant). When multi-tenant support was added in
Phase 4, workspace isolation was added to some endpoints but not to the core task API.

### Fix needed
1. Extract `workspace_id` from JWT in task creation and listing endpoints
2. Set `workspace_id` on all new tasks
3. Filter all task queries by `workspace_id`
4. Add index on `tasks.workspace_id` for query performance

### Prevention
- Add middleware or dependency that automatically extracts workspace context from JWT
- Integration test: user A cannot see user B's tasks

---

## ERROR-022 — Missing workspace isolation in list_workspaces endpoint

**Date:** 2026-03-18
**Severity:** high
**Status:** open
**Found by:** claude_code during security audit
**Affected files:** `backend/nexus/api/workspaces.py`

### What happened
`GET /api/workspaces` returns all active workspaces in the system without filtering by
the authenticated user. Any authenticated user can see all other workspaces.

### Root cause
The endpoint queries `SELECT * FROM workspaces WHERE is_active = true` without any user
filter. JWT contains `workspace_id` but it is not used for authorization.

### Fix needed
1. Extract user identity from JWT
2. Filter workspaces by `owner_id == user_id` or `workspace_members` table membership
3. Return only workspaces the user belongs to

### Prevention
- All list endpoints must include tenant filter
- Integration test: user only sees own workspaces

---

## ERROR-021 — Hardcoded A2A development token in source code

**Date:** 2026-03-18
**Severity:** critical
**Status:** open
**Found by:** claude_code during security audit
**Affected files:** `backend/nexus/gateway/auth.py`

### What happened
The string `"nexus-dev-a2a-token-2026"` is hardcoded in `auth.py:254` and auto-seeded
into the database via `seed_dev_token()`. This token is discoverable in the source code
and automatically created in any environment that runs migrations, including production.

### Root cause
Development convenience: a known token was hardcoded for local testing. No gate to
prevent it from being seeded in production environments.

### Fix needed
1. Remove hardcoded token from source code
2. Gate `seed_dev_token()` behind an environment check (`IS_DEVELOPMENT=true`)
3. Generate dev tokens dynamically with `secrets.token_urlsafe(32)`
4. Audit production database for this token and revoke if found

### Prevention
- grep for hardcoded token strings in CI (TruffleHog already configured in security.yml)
- Seed functions must check environment before creating dev data

---

## ERROR-020 — Hardcoded JWT secret with insecure default value

**Date:** 2026-03-18
**Severity:** critical
**Status:** open
**Found by:** claude_code during security audit
**Affected files:** `backend/nexus/settings.py`

### What happened
`settings.py:43` defines `jwt_secret_key` with a default value of
`"nexus-dev-secret-change-in-production"`. If the `JWT_SECRET_KEY` environment variable
is not set, this default is used. Anyone with access to the source code can forge valid
JWT tokens for any user.

### Root cause
Development convenience: a default value was provided so the app starts without
configuration. No runtime check to reject the default in production.

### Fix needed
1. Remove the default value — make `jwt_secret_key` a required env var (app fails to start without it)
2. OR: generate a random secret at startup if not provided (but warn loudly)
3. Add startup check: if `jwt_secret_key == "nexus-dev-secret-change-in-production"` and
   environment is production, refuse to start

### Prevention
- CI check: scan for hardcoded secret defaults in settings
- Startup validation: reject known insecure defaults outside development mode

**Partial mitigation (2026-03-18):** Startup security check in `app.py` now blocks production deployment if JWT secret is the default value. Full fix requires removing the default entirely (BACKLOG item).

---

## ERROR-019 — Unbounded file read and unsafe code execution in MCP tools

**Date:** 2026-03-18
**Severity:** medium
**Status:** open
**Found by:** claude_code during security audit
**Affected files:** `backend/nexus/tools/adapter.py`

### What happened
Two tool functions have insufficient safety boundaries:

1. `tool_file_read()` (lines 95-112): No file size limit, no path restriction. Agent can
   read arbitrarily large files (DoS via memory exhaustion) or sensitive system files
   (`/etc/shadow`, `.env`).

2. `tool_code_execute()` (lines 115-147): Executes code via `subprocess.run` with `bash -c`
   or `python -c`. Only protection is a 30-second timeout. No network restriction, no
   resource limits, no filesystem sandboxing.

### Root cause
Tools were built for Phase 1 single-user local dev where the operator trusts the system.
Multi-tenant deployment requires stronger sandboxing.

### Fix needed
1. File read: add 10MB size limit, whitelist allowed directories, use `Path.resolve()`
   to prevent path traversal
2. Code execution: deploy behind Docker/nsjail sandbox, add resource limits (CPU, memory),
   restrict network access, log all executed code to audit log

### Prevention
- Add path validation utility function used by all file tools
- Add code execution sandbox configuration to settings
- Integration test: verify file read rejects paths outside allowed directories
- Integration test: verify code execution cannot make network calls

**Partial mitigation (2026-03-18):** `_sanitize_tool_output()` added to `tools/adapter.py` — truncates all tool responses at 50KB. File path validation still needed.

---

## ERROR-018 — A2A gateway did not persist Task to database

**Date:** 2026-03-16
**Severity:** critical
**Status:** fixed
**Found by:** claude_code during Phase 2 completion review
**Affected files:** `backend/nexus/gateway/routes.py`

### What happened
The A2A gateway `submit_task` endpoint generated a `task_id`, published an `AgentCommand`
to Kafka `a2a.inbound` topic, but **never created a Task row in PostgreSQL**. This caused:
1. `result_consumer._update_task_in_db()` couldn't find the task — logged a warning and skipped.
2. CEO's `_create_subtasks()` set `parent_task_id` pointing to a non-existent row — FK violation.
3. `GET /a2a/tasks/{id}/status` returned a hardcoded placeholder instead of real state.

The regular task API (`api/tasks.py:44-59`) correctly created the Task before Kafka publish —
the A2A gateway missed this step.

### Root cause
The gateway was built during Phase 2 Priority Group 7 as a "publish to Kafka and let CEO
handle it" design. The assumption was that CEO would create the task record. But CEO receives
tasks from Kafka and expects the Task row to already exist (same as the regular task API flow).

### Fix applied
1. Added `db_session: AsyncSession` parameter to `submit_task` (Litestar DI injection).
2. Create `Task` record with `source=TaskSource.A2A.value` and `source_agent` from metadata.
3. `flush()` + `commit()` before Kafka publish (same pattern as `api/tasks.py`).
4. Replaced hardcoded `get_task_status` placeholder with real DB query.
5. Added SSE streaming endpoint `GET /a2a/tasks/{task_id}/events`.

### Prevention
- Pattern J (see below) added to Known Patterns
- Integration tests in `test_a2a_gateway.py` now validate DB record creation
- The commit-then-publish pattern is enforced: always persist to DB before Kafka

---

## ERROR-017 — Frontend prod Docker build fails (import.meta.env TypeScript error)

**Date:** 2026-03-14
**Severity:** medium
**Status:** fixed
**Found by:** claude_code during Docker multi-stage build implementation
**Affected files:** `frontend/tsconfig.json`, `frontend/src/vite-env.d.ts`

### What happened
`npm run build` in the Docker prod stage failed with:
```
src/api/client.ts(14,29): error TS2339: Property 'env' does not exist on type 'ImportMeta'.
src/ws/AgentWebSocketProvider.tsx(4,29): error TS2339: Property 'env' does not exist on type 'ImportMeta'.
```
TypeScript didn't know about Vite's `import.meta.env` extension.

### Root cause
Missing `vite-env.d.ts` type declaration file and no Vite client types referenced in
`tsconfig.json`. The dev server worked because Vite injects these types at runtime,
but `tsc` (used by `npm run build`) requires explicit type declarations.

### Fix applied
1. Created `frontend/src/vite-env.d.ts` with `/// <reference types="vite/client" />`
2. Added `"src/vite-env.d.ts"` to `tsconfig.json` `include` array

### Prevention
- Frontend CI job now runs `npx tsc --noEmit` and `npm run build` to catch type errors
- Standard Vite project setup always includes `vite-env.d.ts` — verify on project init

---

## ERROR-016 — Frontend node_modules packaged into Docker image

**Date:** 2026-03-14
**Severity:** medium
**Status:** fixed
**Found by:** user report — Docker build was slow and images were bloated
**Affected files:** `frontend/Dockerfile`, `frontend/.dockerignore`, `docker-compose.yml`

### What happened
Frontend Docker image was 451MB because: (1) No `.dockerignore` existed for the frontend
directory, so host `node_modules/` was sent as part of the Docker build context.
(2) `COPY . .` in the Dockerfile copied the host node_modules into the image alongside
the container's own `npm install` output. (3) Anonymous volume `- /app/node_modules` in
docker-compose.yml was fragile.

### Root cause
Missing `.dockerignore` for the frontend. Single-stage Dockerfile with no dev/prod separation.

### Fix applied
1. Created `frontend/.dockerignore` excluding `node_modules`, `dist`, `.git`
2. Multi-stage Dockerfile: `dev` → `build` → `prod` (nginx, 62MB)
3. Changed anonymous volume to named volume `frontend_node_modules:/app/node_modules`
4. Added `target: dev` to docker-compose.yml

### Prevention
- `.dockerignore` now exists for both backend and frontend
- Multi-stage builds ensure prod images never include dev dependencies
- Named volumes are more predictable than anonymous volumes

## ERROR-015 — In-memory meeting registry not cluster-safe

**Date:** 2026-03-10
**Severity:** medium
**Status:** mitigated
**Found by:** claude_code during Phase 2 PG 5 (meeting room) implementation
**Affected files:** `backend/nexus/kafka/meeting.py`

### What happened
The `MeetingRoom` class uses an in-memory dict `_meeting_registry` to track active meetings.
This works in single-process mode but will lose all meeting state if the process restarts,
and cannot be shared across multiple backend workers.

### Root cause
Phase 2 design choice for simplicity. The meeting registry stores active `MeetingRoom` objects
in a module-level dictionary. Designed for single-worker mode used in current deployment.

### Fix applied
Documented as a known limitation. The registry includes proper cleanup (`close()` method on
MeetingRoom, `close_all_meetings()` on registry). For Phase 3, meetings should use Redis-backed
state to survive restarts and enable multi-worker deployments.

### Prevention
- BACKLOG item for Redis-backed meeting registry (Phase 3)
- MeetingRoom includes timeout guards (300s) and max-round guards (10) to prevent zombie meetings
- `close_all_meetings()` is called during graceful shutdown

---

## ERROR-014 — Unused imports cascade in newly created Phase 2 files

**Date:** 2026-03-10
**Severity:** low
**Status:** fixed
**Found by:** claude_code (IDE linter feedback) during Phase 2 PG 4-7 implementation
**Affected files:** `backend/nexus/kafka/meeting.py`, `backend/nexus/agents/prompt_creator.py`,
`backend/nexus/api/prompts.py`, `backend/nexus/gateway/schemas.py`, `backend/nexus/gateway/auth.py`,
`backend/nexus/gateway/routes.py`, `backend/nexus/tests/integration/test_a2a_gateway.py`

### What happened
Multiple newly created files contained unused imports (`asyncio`, `Any`, `UUID`, `uuid4`,
`AgentRole`, `TaskStatus`, `patch`, `AsyncMock`, `pytest`, `_hash_token`, `Task`,
`A2ACompletionEvent`, `A2AEventStatus`). Ruff linter would flag these.

### Root cause
Files were created with imports that were anticipated to be needed but were not used in
the final implementation. Common pattern when writing code that evolves during development.

### Fix applied
Removed all unused imports across all 7 affected files in multiple cleanup passes.
Verified by IDE lint feedback — all unused import warnings resolved.

### Prevention
- Always verify imports after completing a file
- Run `ruff check --select F401` (unused imports) before committing
- IDE feedback loop catches these incrementally

---

## ERROR-013 — CEO decomposition f-string with JSON braces causes parse errors

**Date:** 2026-03-10
**Severity:** medium
**Status:** fixed
**Found by:** claude_code during Phase 2 implementation
**Affected files:** `backend/nexus/agents/ceo.py`

### What happened
CEO system prompt used f-string with inline JSON example containing braces:
`f"Example: [{{"role": "analyst"...}}]"`. IDE and some Python parsers flagged this as
a syntax error due to nested brace escaping ambiguity.

### Root cause
f-strings require `{{` and `}}` to produce literal braces. Combined with JSON examples
containing multiple nested objects, the escaping becomes fragile and hard to read.

### Fix applied
Changed the JSON example from an f-string to a plain string concatenation. The LLM
prompt template uses `str.format()` or simple concatenation for dynamic parts, keeping
the JSON example as a literal string.

### Prevention
- Pattern: never embed JSON examples in f-strings. Use plain strings for static content.
- Added to code review checklist for agent prompts.

---

## ERROR-012 — Unused imports/variables in Phase 2 agent files

**Date:** 2026-03-10
**Severity:** low
**Status:** fixed
**Found by:** claude_code during Phase 2 implementation
**Affected files:** `backend/nexus/agents/ceo.py`, `backend/nexus/tools/adapter.py`, `backend/nexus/kafka/result_consumer.py`

### What happened
Multiple files had unused imports (`datetime`, `timezone`, `uuid4`) and unused variable
assignments (`add_result`, `commit_result`, `ceo_id`). Would fail ruff lint checks.

### Root cause
Code was written with variables for debugging that were not cleaned up before finalization.

### Fix applied
Removed all unused imports and variable assignments. Verified with `ast.parse()` on all files.

### Prevention
- Run `ruff check` before finalizing any file
- CI enforces ruff linting on every commit

## ERROR-011 — Docker port conflicts with host services

**Date:** 2026-03-08
**Severity:** medium
**Status:** fixed
**Found by:** claude_code during E2E verification
**Affected files:** `docker-compose.yml`

### What happened
`docker compose up` failed to bind ports 5432 and 6379 because the host machine
runs local PostgreSQL (5432) and Redis (6379).

### Root cause
docker-compose.yml used identical host:container port mappings (5432:5432, 6379:6379).
Host services occupied these ports.

### Fix applied
Remapped host ports: postgres `5433:5432`, redis `6380:6379`. Internal Docker networking
unaffected — containers still use standard ports via Docker DNS. See ADR-015.

### Prevention
- ADR-015 documents the port mapping convention
- `docker-compose.yml` comments explain the remapping reason

---

## ERROR-010 — Frontend API path mismatches

**Date:** 2026-03-08
**Severity:** high
**Status:** fixed
**Found by:** claude_code during E2E verification
**Affected files:** `frontend/src/App.tsx` (before decomposition), `frontend/src/api/client.ts`

### What happened
Frontend called `/tasks`, `/approvals` directly. Backend routes are under `/api/` prefix
(`/api/tasks`, `/api/approvals`). All API calls returned 404. Additionally, approval
endpoints used separate `/approve` and `/reject` paths instead of the correct single
`/resolve` endpoint.

### Root cause
Frontend was written before the API router prefix was finalized. The approval API design
changed from two endpoints to one `POST /resolve` with `{ approved: bool }` body.

### Fix applied
Updated all API paths to use `/api/` prefix. Changed approval calls to use
`POST /api/approvals/{id}/resolve` with `{ approved: bool, resolved_by: 'human' }`.

### Prevention
- API client module (`frontend/src/api/client.ts`) centralizes all API paths
- Future: generate TypeScript types from OpenAPI spec to catch mismatches at build time

---

## ERROR-009 — Heartbeat double-serialization causes TypeError

**Date:** 2026-03-08
**Severity:** high
**Status:** fixed
**Found by:** claude_code during E2E verification
**Affected files:** `backend/nexus/agents/base.py`

### What happened
Agent heartbeat loop crashed with `Object of type bytes is not JSON serializable`.
Heartbeat messages never reached Kafka.

### Root cause
The heartbeat code did `json.dumps(hb.model_dump(mode="json")).encode("utf-8")` producing
`bytes`, then passed it to the Kafka producer whose `value_serializer=lambda v: json.dumps(v).encode("utf-8")`
tried to JSON-serialize the bytes object. Double serialization.

### Fix applied
Pass `hb.model_dump(mode="json")` (a `dict`) directly to `producer.send_and_wait()`.
The producer's `value_serializer` handles JSON encoding.

### Prevention
- Pattern documented: never pre-serialize when using a producer with `value_serializer`
- Same pattern applies to all Kafka `publish()` calls via `producer.py`

---

## ERROR-008 — Task not persisting to DB before Kafka consumer processes it

**Date:** 2026-03-08
**Severity:** critical
**Status:** fixed
**Found by:** claude_code during E2E verification
**Affected files:** `backend/nexus/api/tasks.py`

### What happened
Task created via `POST /api/tasks` was flushed to DB but not committed before the Kafka
message was published. CEO agent consumed the Kafka message and queried the DB, but the
task didn't exist yet (uncommitted transaction).

### Root cause
Relied on Litestar's auto-commit, which commits after the response is sent. The Kafka
consumer processes the message before the HTTP response completes.

### Fix applied
Added explicit `await db_session.commit()` after `db_session.flush()` and before
`publish()` in `tasks.py`. See ADR-016.

### Prevention
- ADR-016: explicit commit before Kafka publish is now a project convention
- Any API handler that writes to DB then publishes to Kafka must commit first

---

## ERROR-007 — sa_orm_sentinel column missing from Alembic migration

**Date:** 2026-03-08
**Severity:** critical
**Status:** fixed
**Found by:** claude_code during E2E verification
**Affected files:** `backend/alembic/versions/001_initial_schema.py`

### What happened
All database queries failed with `UndefinedColumnError: column "sa_orm_sentinel" does not exist`.
Health check, task creation, agent queries — everything touching the DB was broken.

### Root cause
Advanced Alchemy's `UUIDBase` and `UUIDAuditBase` automatically add a `sa_orm_sentinel`
column to ORM models. The hand-written Alembic migration did not include this column in
any of the 9 tables.

### Fix applied
Added `sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True)` to all 9 tables
in `001_initial_schema.py`.

### Prevention
- Documented in project memory: Advanced Alchemy base classes add `sa_orm_sentinel`
- Future migrations should be auto-generated with `alembic revision --autogenerate`
  to catch ORM-added columns

---

## ERROR-006 — AnthropicModel rejects api_key parameter in pydantic-ai 0.5.x

**Date:** 2026-03-08
**Severity:** high
**Status:** fixed
**Found by:** claude_code during E2E verification
**Affected files:** `backend/nexus/llm/factory.py`

### What happened
`ModelFactory.get_model()` passed `api_key=settings.anthropic_api_key` to
`AnthropicModel()`. pydantic-ai 0.5.x raised `TypeError: __init__() got an unexpected
keyword argument 'api_key'`.

### Root cause
pydantic-ai 0.5.x changed the model constructor API. API keys are now read from
environment variables automatically (`ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`).

### Fix applied
Removed `api_key` parameter from `AnthropicModel()` and `GeminiModel()` calls in
`factory.py`. Keys are set via env vars in docker-compose.yml.

### Prevention
- ADR-014 documents the pydantic-ai version pin and API key behavior
- Version pinned to 0.5.x to prevent future breakage

---

## ERROR-005 — pydantic-ai 0.6+ incompatible with anthropic SDK 0.84+

**Date:** 2026-03-08
**Severity:** critical
**Status:** fixed
**Found by:** claude_code during E2E verification
**Affected files:** `backend/pyproject.toml`

### What happened
Backend failed to start with `ImportError` when pip resolved pydantic-ai 0.6+ with
anthropic 0.84.0. pydantic-ai 0.6+ imports `UserLocation` from
`anthropic.types.beta.beta_web_search_tool_20250305_param`, but anthropic 0.84.0 renamed
it to `BetaUserLocationParam`.

### Root cause
Breaking change in anthropic SDK 0.84.0 that pydantic-ai 0.6+ was not updated to handle.
No compatible combination of pydantic-ai 0.6+ and any anthropic SDK version exists.

### Fix applied
Pinned `pydantic-ai[anthropic,google]>=0.5.0,<0.6.0` and `anthropic>=0.80.0,<0.83.0`
in `pyproject.toml`. See ADR-014.

### Prevention
- Version pins in pyproject.toml prevent pip from resolving to broken combinations
- ADR-014 documents the constraint and future upgrade path

---

## ERROR-004 — structlog.get_level_from_name does not exist

**Date:** 2026-03-08
**Severity:** high
**Status:** fixed
**Found by:** claude_code during E2E verification
**Affected files:** `backend/nexus/app.py`, `backend/nexus/agents/runner.py`

### What happened
Backend crashed at startup with `AttributeError: module 'structlog' has no attribute
'get_level_from_name'`. Both `app.py` and `runner.py` called this non-existent function.

### Root cause
`structlog.get_level_from_name()` was assumed to exist but does not. The function was
likely confused with an internal or deprecated API.

### Fix applied
Replaced with `getattr(logging, settings.log_level.upper(), logging.INFO)` using
Python's standard `logging` module to convert level name strings to integers.

### Prevention
- Pattern documented in project memory for future structlog usage
- `import logging` added to both files

---

## ERROR-003 — PRE-BUILD WARNING: Irreversible tool action before approval flow exists

**Date:** 2026-03-07
**Severity:** critical
**Status:** fixed
**Found by:** claude_code during pre-build documentation review
**Affected files:** `nexus/tools/adapter.py`, `nexus/tools/guards.py`, `nexus/db/models.py`

### What happened
This is a pre-build warning, not a discovered bug. CLAUDE.md §23 Prevention Rule 4
identifies a critical risk: if any agent runs before `require_approval()` and the
`human_approvals` table exist, irreversible tools (file_write, git_push, send_email)
could execute without human consent.

### Root cause
The approval flow is infrastructure, not a feature. If treated as a Phase 2 feature,
agents in Phase 1 testing could trigger irreversible actions with no safety gate.

### Fix applied
`require_approval()` guard built in Phase 0. `human_approvals` table deployed in
`001_initial_schema.py`. Approval UI with approve/reject buttons operational since Phase 1.
All 3 irreversible tools (`file_write`, `git_push`, `send_email`) guarded. 6 unit tests
in `test_guards.py`. `tool_hire_external_agent` added in Phase 3 with same guard.

### Prevention
- Phase 0 gate: `human_approvals` table exists before any agent runs — PASSED
- Phase 1 gate: `require_approval()` guard unit tested — PASSED
- CI: ruff + mypy + pytest enforce guard chain on every commit

---

## ERROR-002 — PRE-BUILD WARNING: Unbounded agent loop cost explosion

**Date:** 2026-03-07
**Severity:** critical
**Status:** fixed
**Found by:** claude_code during pre-build documentation review
**Affected files:** `nexus/agents/base.py`, `nexus/llm/usage.py`, `nexus/redis/clients.py`

### What happened
This is a pre-build warning, not a discovered bug. CLAUDE.md §23 Prevention Rule 2
identifies a critical risk: without token budget enforcement, a single multi-agent task
could burn $50+ in LLM API costs before anyone notices. Agent loops (tool call -> LLM ->
tool call) can iterate indefinitely if not bounded.

### Root cause
LLM API calls have real cost. Without a hard cap checked before every call, there is no
upper bound on spending per task or per day.

### Fix applied
All 5 mitigations implemented:
1. Redis db:1 token tracker: `token_budget:{task_id}` with 50k default — Phase 1
2. Daily spending cap: `daily_spend:{date}` with $5/day hard limit — Phase 1
3. `AgentBase._check_budget()` in guard chain before every LLM call — Phase 1
4. At 90% budget: task pauses, publishes to `human.input_needed` — Phase 1
5. 20-tool-call limit per task via `_wrap_tools_with_counter()` — Phase 2 (ADR-028)
6. Redis failure safe degradation added in Phase 3 — budget checks return True on Redis error
7. Per-agent cost tracking: `GET /analytics/costs/{agent_id}` — Phase 2

### Prevention
- Phase 0 gate: Redis token tracker writable — PASSED
- Phase 1 gate: `_check_budget()` unit tested — PASSED
- Chaos test: budget exceeded scenario verified — PASSED (Phase 3)

---

## ERROR-001 — PRE-BUILD WARNING: Building orchestration before core agent loop works

**Date:** 2026-03-07
**Severity:** high
**Status:** fixed
**Found by:** claude_code during pre-build documentation review
**Affected files:** `nexus/agents/base.py`

### What happened
This is a pre-build warning, not a discovered bug. CLAUDE.md §23 Prevention Rule 1
identifies a high risk: if multi-agent orchestration (CEO delegation, meeting rooms,
QA pipeline) is built before the core single-agent loop is proven reliable, a bug in
AgentBase will cascade to every agent and invalidate weeks of work.

### Root cause
AgentBase is the most critical class in the system. Every agent inherits from it.
Its guard chain (idempotency -> budget -> load memory -> handle_task -> write memory ->
publish -> broadcast) must work flawlessly before any multi-agent interaction is attempted.

### Fix applied
Phase 1 produced one working Engineer Agent with proven guard chain. 50-task stress test
passed at 100% (50/50) on 2026-03-08. Multi-agent orchestration built in Phase 2 only
after gate cleared. Phase 2 20-task stress test also passed at 100%.

### Prevention
- Phase 1 DoD: 50-task stress test at >= 90% pass rate — PASSED (100%)
- Phase 2 gate: 20-task stress test — PASSED (100%)
- Phase 3 gate: chaos tests across 8 failure scenarios — PASSED

---

## Known Patterns to Watch For

These patterns have caused problems in agentic systems generally.
Check for them during code review and testing.

### Pattern A — Memory write after publish

**Risk:** Agent publishes result to Kafka before writing episodic memory.
If memory write fails, the task appears complete but has no memory record.
**Watch for:** Any code where `kafka.publish()` appears before `memory.write_episode()`.
**Required order:** memory.write_episode() → kafka.publish() → always.

### Pattern B — Silent exception swallow

**Risk:** `except Exception: pass` hides failures. Tasks appear to complete but
produced no useful output. No log entry. No trace. Impossible to debug.
**Watch for:** Any bare `except` block without a log statement and re-raise.
**Required pattern:** Always log + (handle or re-raise).

### Pattern C — Sync I/O in async context

**Risk:** Blocking call inside an async function freezes the entire event loop.
All other tasks waiting on the event loop are blocked.
**Watch for:** `requests.get()`, `open()`, `time.sleep()` inside async functions.
**Required pattern:** Use async equivalents or wrap with `asyncio.to_thread()`.

### Pattern D — Duplicate Kafka message processing

**Risk:** Kafka delivers messages at-least-once. Without idempotency keys,
the same task can be processed twice. Double LLM calls, double memory writes,
double tool calls (possibly double emails sent).
**Watch for:** Any Kafka consumer that doesn't check a Redis idempotency key first.
**Required pattern:** Check `idempotency:{message_id}` in Redis db:3 before processing.

### Pattern E — Token budget not checked before LLM call

**Risk:** Agent makes LLM calls without checking remaining budget. Task exceeds
the per-task token limit, cost spikes, and the agent doesn't pause for human input.
**Watch for:** Any `await self.llm.run(...)` not preceded by `await self._check_budget(...)`.
**Required pattern:** Always _check_budget() → then llm.run().

### Pattern F — Irreversible tool without approval gate

**Risk:** Agent writes a file, sends an email, or pushes code without human approval.
Action cannot be undone.
**Watch for:** Any tool in `adapter.py` that has side effects but no `require_approval()` call.
**Required pattern:** Every tool with side effects in the real world MUST call `require_approval()`.

### Pattern G — Hardcoded Kafka topic string

**Risk:** Topic string typo is only caught at runtime, not at lint time. Misrouted
messages are silently dropped or go to wrong consumers.
**Watch for:** Any string literal matching a known topic pattern (e.g., `"agent.commands"`)
outside of `kafka/topics.py`.
**Required pattern:** Always `Topics.AGENT_COMMANDS`, never `"agent.commands"`.

### Pattern H — Subtask forwarding race condition

**Risk:** Subtask completes before CEO finishes writing tracking state to Redis working
memory. Result consumer forwards aggregation command to CEO, but CEO can't find tracking
data. Subtask result is lost or task hangs.
**Watch for:** Any code path where a subtask response is processed before `set_working_memory()`
completes in the CEO decomposition path.
**Required pattern:** CEO must `await set_working_memory()` before dispatching any subtask.
Redis write must be confirmed before Kafka publish.

### Pattern I — JSON parsing from LLM output

**Risk:** LLM returns JSON wrapped in markdown code blocks (`` ```json ... ``` ``),
or with preamble text before the JSON. Direct `json.loads()` fails.
**Watch for:** Any agent that expects structured JSON from LLM output (CEO decomposition,
QA review). Raw `json.loads(output)` will fail on markdown-wrapped responses.
**Required pattern:** Strip markdown code block markers before parsing. Have a fallback
for non-JSON responses (CEO: default to single engineer subtask; QA: default to approved).

### Pattern J — External gateway must persist to DB before Kafka publish

**Risk:** An external-facing gateway (A2A, webhook, etc.) publishes a task to Kafka
without first creating a Task record in PostgreSQL. Downstream consumers (CEO, result
consumer) expect the Task row to exist. FK violations, lost results, and orphaned tasks.
**Watch for:** Any new gateway or inbound endpoint that publishes to Kafka. Must follow
the same commit-then-publish pattern as `api/tasks.py`.
**Required pattern:** `db_session.add(task)` → `flush()` → `commit()` → THEN `kafka.publish()`.
See ERROR-018 for the original incident.

### Pattern K — Core vs integration boundary

**Risk:** Core infrastructure (`core/kafka`, `core/redis`, `core/llm`) must always be available. Pluggable integrations (`integrations/keepsave`, `integrations/a2a`, `integrations/temporal`, `integrations/eval`) must degrade gracefully. Never put a pluggable service in `core/`. Never put a system-critical service in `integrations/`.
**Watch for:** New modules added to `core/` that are not strictly required for the system to function, or new modules added to `integrations/` that the system cannot operate without.
**Required pattern:** If the system breaks without it, it belongs in `core/`. If the system degrades but continues without it, it belongs in `integrations/`.

---

*Last updated: 2026-10-13 (company foundation validation)*
*Next error ID: ERROR-057*
*Pre-build warnings (ERROR-001 through ERROR-003): FIXED.*
*Security audit findings (ERROR-019 through ERROR-025): ALL FIXED (2026-03-21).*

### Phase 6 Security RCA Resolution Summary (2026-03-21)

| Error | Severity | Fix | File |
|-------|----------|-----|------|
| ERROR-019 | MEDIUM | Added 10MB file size limit, `Path.resolve()` traversal prevention, allowed dir whitelist, 256MB memory + 30s CPU limits on code execution | `tools/adapter.py` |
| ERROR-020 | CRITICAL | Removed default JWT secret. Required via env var. Startup blocks on weak secrets. | `settings.py`, `app.py` |
| ERROR-021 | CRITICAL | Removed hardcoded `"nexus-dev-a2a-token-2026"`. Dynamic generation via `secrets.token_urlsafe(32)`. Dev-only gating. | `a2a/auth.py` |
| ERROR-022 | HIGH | `list_workspaces` filtered by user via WorkspaceMember join. `create_workspace` uses JWT owner_id. `get_workspace` verifies membership. | `api/workspaces.py` |
| ERROR-023 | HIGH | All 5 task endpoints now extract `workspace_id` from JWT and scope queries. `create_task` sets workspace_id on new tasks. | `api/tasks.py` |
| ERROR-024 | HIGH | Slug sanitized via regex, collision detection with `-N` suffix, `_generate_unique_slug()` helper. | `api/workspaces.py` |
| ERROR-025 | HIGH | Removed `resolved_by` from request body. Extracted from JWT. Unauthenticated callers rejected. Approvals scoped to workspace. | `api/approvals.py` |
