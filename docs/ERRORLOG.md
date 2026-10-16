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

## ERROR-179 — Fault-record rejection loses its original reason and candidate

**Date:** 2026-10-16
**Severity:** medium
**Status:** open
**Found by:** actual current-V9 Source2 first parent case and independent retained-file audit
**Affected files:** private FaultSnapshot validator/collector/failure diagnostics

Source2 passes382 finite checks and real setup/audit, then the first native case
fails1/45.975s after one tool attempt. A clean complete3,413-byte collector report
records model-level FaultSnapshot ValidationError; exact reason and original
candidate are absent. Actual private result validates as outcome_unknown with
no commands/artifacts/logs/containment. No physical fault or observer ref exists.

One read-only failure audit confirms477 rows, unknown intent and USD0.010000 hold,
null actual billing, Work unknown/fence2/unleased and other four cases unchanged.
The wave stops. Original parent timing, whole-tree retirement and unique failing
predicate cannot be inferred or repaired with later observations. Metadata
recovery is not run without its required witness and is unnecessary for the
already released lease.

Independent diagnosis enumerates ten same-type root raises plus nested/window
validation. Capture closed per-predicate reasons and, when safely available under
the original end, a separate complete bounded UNVALIDATED candidate. It must never
be a FaultRef or accepted physical witness. No predicate/clock/limit relaxation
or speculative retry. Actual audit SHA6b8d9d93… and diagnosis SHA5eaab6da… are
linked from the current progress page; minimal source repair is in progress.

---

## ERROR-178 — Staging forward misses dynamically constructed operator suffixes

**Date:** 2026-10-16
**Severity:** low
**Status:** fixed
**Found by:** actual Source2 staging preflight
**Affected files:** external staging command only

Literal filename forwarding misses `entry+'_1.py'` and a preflight `-1.json`
suffix. The first guard compares the old operator to the new expected hash and
stops before any command/database/runtime-root creation. Preserve that control.
A new control changes only its output root and these two suffix constants; AST
comparison proves that scope, actual rendered hashes/absences pass, staging
completes0/1.804s and direct setup completes0/48.378s. Source2 frozen code,
configuration, actions and windows are unchanged by this staging correction.

Validate rendered concatenated/f-string names as well as whole literal paths.

---

## ERROR-177 — Namespace AST forward misses a formatted preflight suffix

**Date:** 2026-10-16
**Severity:** low
**Status:** fixed (unfrozen assembly; qualification pending)
**Found by:** Root literal-only namespace comparison
**Affected files:** external Source2 candidate assembler

The first copy stops at an AST assertion after865 files: the text forward changes
a quoted `-1.json`, while its Constant forward leaves that value unchanged. A
second prewrite comparison catches the same suffix inside a formatted string.
Preserve the first partial tree and failed second script. Both are unfrozen;
neither creates a final manifest, published operator, database or authority.

Inspect all three suffix occurrences, then apply the same literal transformation
to ordinary and formatted strings. Corrected prewrite AST comparison/copy passes
for1,664 backend files and seven outside files. Three backend namespace surfaces
change; the parent-age overlay and actual qualification remain separate. Validate
all transformed input ASTs before target writes.

---

## ERROR-176 — Parent fault scheduling adds age after startup

**Date:** 2026-10-16
**Severity:** medium
**Status:** fixed (source scheduling; full native qualification remains open)
**Found by:** Root passive timing and independent source inspection
**Affected files:** private negative operator scheduling

The inside entry repeats source/packet/import/pre-case work, then sleeps a full
36s before bootstrap. A comparable actual passive10.627s plus36 exceeds the45s
parent. This is credible pre-issuance infeasibility, not an observed native failure;
no V9 case is launched. Controller start predates scope activation and cannot
precisely substitute for actual parent age.

A prospective helper must sample the fixed manager unit's actual active-enter
clock/invocation, wait only remaining actual age and require the unchanged full
bootstrap to match the same unit/invocation/start/deadline. Derive age36.250001s
from the original strict timing inequality without relying on bootstrap cost.
Keep45/60/1/10/25, original ends, quotas and all physical predicates unchanged.
Preserve Source1. The correction passes74 focused checks and an independent
two-counterexample forward review after an early target-feasibility guard is
added. Coherent Source2 passes382 checks/strict-lint-format45 and reaches one
actual native issuance; its later independent FaultSnapshot failure is tracked
in ERROR-179. No parent-expiry qualification is claimed.

---

## ERROR-175 — Packet producer ends without its final validation receipt

**Date:** 2026-10-16
**Severity:** low
**Status:** mitigated
**Found by:** Root actual packet preparation
**Affected files:** external parent packet control and Root observation

Outer35s exits124 after writing the preflight and packet, without the producer's
final round-trip/terminal receipt. The precise stopping phase is unknown. A later
imports-only cold diagnostic takes18.663s, which does not uniquely attribute the
original timeout. Preserve its control, original clock and partial result files.

Root initially incorrectly reports both files absent; actual named-file inspection
corrects that statement and preserves the incorrect JSON report with a correction.
A separate published passive CLI in the exact declared scope environment validates
the unchanged packet in10.627s, exit0/empty stderr. No native case/permit is issued.
Inspect actual paths before reporting absence; distinguish startup and operation
envelopes, and a later passive check from completion of the original producer.

---

## ERROR-174 — Diagnostic exec namespace cannot resolve setup model annotations

**Date:** 2026-10-16
**Severity:** medium
**Status:** fixed (actual direct setup; native qualification pending)
**Found by:** Root actual fresh V9 all-five setup
**Affected files:** external `launch-setup-1.py` diagnostic wrapper

Setup exits1 in3.72s at `Manifest.model_validate_json`: Pydantic reports
`Manifest` incomplete because `Literal` cannot be resolved. The traceback is
before company schema installation or any native case; preparation already created
the empty target database. Complete stdout is empty;
complete stderr and safe exception metadata are retained with the original clock.

The wrapper compiles verified script bytes into a new dictionary claiming
`__name__='__main__'`, without registering that dictionary as the actual module.
The script uses postponed annotations. Its imported names therefore differ from
the module namespace Pydantic consults. Direct passive CLI checks exercise the
normal module path and do not cover this wrapper-only failure.

An independent definitions-only reproduction confirms the same error for the
unregistered namespace and successful model validation with a registered module.
Receipt SHA-256 is
`5342cfab21af47784f4ccd732e463a9789a2c80f5d040c6e4b48272417d474c9`.
Use a normal direct pinned CLI or a correctly registered module. An independent
read-only snapshot confirms the prepared target has no company objects or authority
windows. A separately frozen direct CLI then completes all-five setup0/68.827s;
independent file/SQL audit passes. Preserve the failed wrapper/control and original
clock. No existing action/window is renewed, and no native qualification follows.
Test the exact launch mechanism before live setup. See [actual evidence](company-system/CURRENT_V9_SETUP_AND_PARENT_AGE_CHECKPOINT_2026-10-16.md).

---

## ERROR-173 — Passive setup invocation omits required source digest

**Date:** 2026-10-16
**Severity:** low
**Status:** fixed
**Found by:** Root published V9 setup passive check
**Affected files:** external operator invocation

The first `--check-only` invocation omits mandatory `--source-sha` and argparse
exits2 before backend imports, database access or scope creation. The failed
receipt remains preserved. The corrected passive invocation supplies the frozen
source digest and completes0 in1.07s with database_opened=false,
scope_started=false and source_files1664. Source/E bytes and authority are unchanged.

Render required arguments from published help for both passive and release
commands. A passing passive invocation does not qualify a different wrapper's
execution namespace or prove live setup.

---

## ERROR-172 — Diagnostic output and late parsing mask the retained first denial

**Date:** 2026-10-16
**Severity:** medium
**Status:** open
**Found by:** independent file-only cancellation triage
**Affected files:** private case entry, negative observer and transport

The observer waits for an empty tree before decoding a completed collector report.
It therefore reports TimeoutError before adopting the actual native cancellation.
The retained full capture also contains a 183-byte warning before 5308 bytes of JSON
and 108 bytes of launcher stderr. These are independent latent framing rejections;
the original observer does not reach their validation before its timeout.

Give the private collector a dedicated control-only stdout, retain complete bounded
stderr, and validate a completed canonical report before waiting for retirement.
Do not strip mixed historical output into accepted wire or infer physical success
from a decoded denial. Meaningful finite framing/first-cause tests precede a new
source package. The old capture, predicates and failed wave remain unchanged.

---

## ERROR-171 — Runtime-client cleanup leaves the owned container tree alive

**Date:** 2026-10-16
**Severity:** high
**Status:** fixed (source; native V9 qualification pending)
**Found by:** actual cancellation retirement qualification
**Affected files:** `backend/nexus/builder/contained_process.py` and owned lifecycle

The native guard detects cancellation in 228179 microseconds, then the runtime
finalizer kills/reaps only the Podman client. Conmon, payload and three descendants
remain alive at the original 10 s oracle bound. The stopped-wave audit correctly
denies qualification; later stopped/PID0/Scope.success facts cannot repair it.

Add a bounded running-stop boundary issued only by the original opaque owned
context and full immutable container identity. Stop before context close, preserve
original end/first denial/task and child owners, and retain incomplete/unsealed
uncertainty. Existing cleanup v1 is stopped-object removal and cannot confer this
new authority. No remove, replacement execution permit or financial reset occurs.
Version the changed method, preserve old histories, then requalify in a fresh
namespace. Finite ownership/cancellation/deadline tests and actual whole-tree
qualification are separate requirements. The source result is recorded below;
actual V9 qualification remains open.

Source repair now passes 4,307 coherent backend tests, configured nonsilent
strict/lint/format on 11 files and independent reproduced counterexamples. Candidate1's
before-first-stop seal substitution and normal-drain cancellation timing gaps
are preserved as failed tests; candidate2 fixes them and late issued-child
ownership. Current V9 remains unconfigured. This fixes the source boundary;
it does not repair the old failed wave or establish a new physical pass. See
[the V9 source checkpoint](company-system/NATIVE_OWNED_STOP_V9_SOURCE_CHECKPOINT_2026-10-16.md).

---

## ERROR-170 — Read-only capture guard consumes its launcher's output

**Date:** 2026-10-16
**Severity:** low
**Status:** fixed
**Found by:** actual passive host capture
**Affected files:** private read-only capture helper

An overbroad stdout-file guard rejects the launcher's already-open outer stdout
before the first query. The failed control and its original clock remain intact.
A fresh capture checks only its eight query outputs and terminal/failure objects;
it completes all eight bounded read-only commands in 2.07s. No native attempt,
lease or SQL action occurs in either capture. Record exact owned output names
and keep wrapper streams separate from the consumption guard.

---

## ERROR-169 — Descriptive packet retains the previous source-file count

**Date:** 2026-10-16
**Severity:** low
**Status:** fixed
**Found by:** published E4 passive packet check
**Affected files:** private metadata-only packet producer

The producer writes count1653 after two new helper/test files make the exact
manifest closure1655. Both unchanged passive guards reject it before backend
import, controller creation or native issuance. The failed packet is preserved
by an inode-preserving archive rename. A new packet changes only the descriptive
count; source, code, config, action, preflight, grants and original windows are
unchanged. Full library validation and actual published CLI check pass. The
corrected packet subsequently reaches the separately frozen native case.

Derive counts from the SHA-pinned manifest and verify the actual closure. A
saved future producer also validates the published packet before reporting
completion; that full producer remains unexecuted. No approval or allowance is
reset by the metadata repair.

---

## ERROR-168 — First native fault attempt lacks a usable sample witness

**Date:** 2026-10-16
**Severity:** medium
**Status:** open
**Found by:** actual current-V8 parent-expiry qualification
**Affected files:** private negative collector and operator composition

### What happened
The first actual case fails after one issued tool attempt. Native same-call
diagnostics retain `ValidationError` in the sampling path with zero samples.
The outside report records `ValueError` and no fault/issued/post-stop ledger.
The intent and cost hold remain unknown; the other four cases never issue.

### Root cause
The precise original failing validator is not retained. A timing-precondition
hypothesis is under source-only investigation; later host absence cannot supply
the missing original sample or prove timer attribution.

### Fix applied
No runtime repair or retry is claimed. Stop the wave and preserve the exact
source, packet, original windows, unknown hold, stopped container and diagnostics.
The current recovery entry cannot run without its required witness inputs.

### Prevention
Retain the actual owned collector capture and safe same-catch failure metadata.
Check causal timing eligibility before a future qualification issues an effect;
do not relax the original thresholds or reinterpret this attempt as a pass.

---

## ERROR-167 — Real fixture spec inherits V1 against declared V2 policy

**Date:** 2026-10-16
**Severity:** medium
**Status:** fixed
**Found by:** second actual setup and real-helper pure reproduction
**Affected files:** private negative registration helper and its composition test

### What happened
Setup returns source/plan/action authorization, then final config validation
rejects the execution spec. No native attempt or intent is issued.

### Root cause
The real helper omits `runtime_recipe`; `BuilderExecutionSpec` defaults to V1,
while its policy declares V2. The synthetic fixture sets V2 explicitly and misses
this composition error. The descriptive-policy guard correctly rejects it.

### Fix applied
A fresh two-file correction binds the spec recipe to its declared policy and
tests complete real-helper configuration. Source4 actual all-five setup then
completes with exit code 0 in 14.61s. The old action and held USD0.010000 reservation stay intact;
the corrected proposal hash differs. Native fault qualification remains open.

### Prevention
Exercise the real helper chain and exact descriptive-policy binding before
claiming fixture compatibility; do not weaken the guard or reuse old approval.

---

## ERROR-166 — Namespace forward misses unit diagnostic text

**Date:** 2026-10-16
**Severity:** low
**Status:** fixed
**Found by:** second preparation's read-only checks
**Affected files:** Root's private staging command text

### What happened
The new unit argument names namespace2, but its expected error text still names
namespace1. Preparation stops after three read-only commands, before any target
database or runtime-root creation.

### Root cause
The mechanical substitution covers the unit argument but misses its duplicated
diagnostic literal.

### Fix applied
Preserve that control operation. A new control corrects the one literal and has
an exact AST-expression check against the retained actual stderr; staging then
completes0. The target namespace remains unissued until that successful staging.

### Prevention
Derive expected diagnostics from the rendered unit argument in the next recipe;
keep consumed control outputs immutable.

---

## ERROR-165 — Generated bytecode enters an unfrozen source tree

**Date:** 2026-10-16
**Severity:** low
**Status:** fixed
**Found by:** final source-closure guard before publication
**Affected files:** private source-only probe environment

### What happened
The guard finds122 generated `.pyc` files beyond the1,653 declared files.
No source manifest or E2 publication occurs at that failed guard.

### Root cause
Source-only imports generated local caches; the exact originating probe is not
attributed. Disabling bytecode writes alone does not prevent reading an existing
cache, so earlier runtime checks have a narrower provenance claim.

### Fix applied
Preserve all122 files outside the source with hashes. Repeat289 focused and10
cross-seed boundary checks using empty cache prefixes; all pass. Final source
closure contains only the declared files.

### Prevention
Set bytecode controls before interpreter startup, verify exact closure and keep
runtime-check provenance separate from source static checks.

---

## ERROR-164 — Unordered controller sets treated as raw ordered lists

**Date:** 2026-10-16
**Severity:** medium
**Status:** fixed
**Found by:** fresh-namespace snapshot test and exact capability-clause reproduction
**Affected files:** private fault contracts and packet comparison, plus paired tests

### What happened
An unchanged typed snapshot re-encodes its controller set in a different array
order, changing its SHA. Raw capability dict equality also rejects an equivalent
permutation and accepts integer1 as equal to booleantrue.

### Root cause
Unordered typed sets cross a JSON array representation without stable field
serialization; the preflight compares raw dict values instead of strict DTOs.

### Fix applied
Sort only the private fault snapshot's typed kernel-controller set in JSON mode.
Validate and compare typed capabilities at preflight. Preserve native parent wire,
ordered tuples and all actual raw-SHA/deadline checks. Finite and cross-seed checks
pass; production kernel contracts and historical profiles remain unchanged.

### Prevention
Test real encode/decode boundaries and strict scalar types across process hash
seeds. Do not sort arbitrary arrays or remove raw-byte binding checks.

---

## ERROR-163 — Static import environment narrowed transitive diagnostics

**Date:** 2026-10-16
**Severity:** medium
**Status:** fixed
**Found by:** Root and independent source reviewer during coherent fixture checks
**Affected files:** private qualification environment and ledger catalog adapter;
production migration source unchanged

### What happened
An explicit target check passed with `PYTHONPATH=.` while the coherent nonsilent
check exposed seven imported SQLAlchemy DDL typing errors. Fresh reciprocal
checks isolated the environment difference on unchanged source.

### Root cause
Pinned mypy1.20.2 treated the duplicate backend import path as a package path and
silenced imported non-root module diagnostics. Cache and `MYPYPATH` were not the cause.

### Fix applied
Final configured strict checks unset `PYTHONPATH`. The fixture uses fixed catalog
security sets with a pure AST comparison instead of importing migration installers
only for their literals. Nonsilent strict38 passes; no import suppression is added.

### Prevention
Retain exact static environment and target scope; runtime/pytest import flags are
separate. Reciprocal logs and source pins remain in the dated evidence folder.

---

## ERROR-162 — First native-fault fixture setup stops after source registration

**Date:** 2026-10-16
**Severity:** medium
**Status:** fixed
**Found by:** actual bounded setup after source-only checks
**Affected files:** private `current_v8_negative_sources.py` fixture adapter

### What happened
Actual normal001–016 installation succeeds, then the first company's setup stops
with `ValueError` after its first Brain source registration. No fault action is
issued. Completed-call hashes and schema metadata survive in the failure output.

### Root cause
The candidate reader compares an actual `SourceRecord` to its base registration
model and would unpack record-only fields into a snapshot. Controlled reproduction
is in progress; the original error message/traceback was not retained, so the
original exact branch is not independently reconstructed from stdout alone.

### Fix applied
Preserve the used Source2/database/run namespace. Reproduce the real returned DTO
through the source registry, then repair only the fixture projection in a fresh
component.20 focused checks pass and fresh Source3 actual ingestion crosses the
old failure point. Its later recipe mismatch is ERROR-167. No reset or retry of
the consumed original attempt occurs.

### Prevention
Test adapters with actual returned record types as well as base request models;
do not weaken production validation to accommodate a fixture.

---

## ERROR-161 — Successful manual reuse omitted stderr from its receipt

**Date:** 2026-10-16
**Severity:** medium
**Status:** fixed
**Found by:** independent source reviewer before actual reuse
**Affected files:** private reuse Source2 `cas_recipe.py`, `cas_reuse_receipt.py`
and two focused test modules; primary production source unchanged

### What happened
The first held reuse recipe retained successful stdout but omitted successful
stderr. A warning could therefore disappear from otherwise successful evidence.
The original Source1 review is unfavorable and no Source1 actual run was issued.

### Root cause
The success receipt contract covered only stdout; failure diagnostics alone did
not preserve stderr from a zero-exit command.

### Fix applied
Fresh Source2 retains both complete streams with explicit decimal lengths and
canonical base64, including empty stderr. Each stream is capped at 16 KiB;
overflow rejects success. FD3 control remains separate. Two meaningful parser
failures precede the repair; 57 finite checks, configured strict/Ruff and independent
forward review pass. The separate actual reuse retains 43-byte stdout and explicit
empty stderr, with favorable FILE audit. Original Source1 stays preserved.

### Prevention
Check complete nonempty/empty stderr, warning propagation, missing/truncated/count/
overflow records and control-looking bytes before freezing a new manual recipe.
See [actual reuse evidence](company-system/CACHE_READONLY_REUSE_CHECKPOINT_2026-10-16.md).

---

## ERROR-160 — Selected template equated manifest and configuration digests

**Date:** 2026-10-16
**Severity:** high
**Status:** fixed (source; native execution pending)
**Found by:** parallel post-import dependency review and finite primary-validator repro
**Affected files:** builder/selected_strategy_contracts.py and synthetic selected fixture

### What happened
The actual retained image reference uses manifest digest c4d552… while its local
configuration/image ID is8f3dff…. Both lower runtime/policy models validate, but
the selected-template suffix-equality guard rejects that distinct pair. An
otherwise equalized synthetic control passes; the original fixture masks the join.

### Root cause
The guard compares identifiers for two different OCI objects. The pinned manifest
contains the actual configuration correspondence; equality does not represent it.

### Fix applied
Use one exact trusted architecture/reference/manifest/configuration pair.
No wildcard, generic inequality allowance or substituted identity.
Keep runtime/native image observation, canonical policy and capability checks.
The original finite repro and1failed2passed result remain preserved.

### Prevention
The distinct-real-pair positive and wrong-reference/ID/cross-pair denials pass.
Preserve old raw golden wires. Full coherent regression passes4,247 units and
independent source review is favorable. Complete new runtime/template pins before fresh S.

---

## ERROR-159 — Parent diagnostic publication could cross its original end

**Date:** 2026-10-16
**Severity:** medium
**Status:** fixed (private source; fresh actual preparation observed)
**Found by:** independent finite telemetry review
**Affected files:** private cas_parent_trace.py and ordinary diagnostic publication tests

### What happened
Summary validation could cross the original clock after an early check and before
a kernel or ordinary failure-tail State write. A later caller check raised only
after publication. The manual collector also retained ERROR-158's visible-group
interval. Three exact peer counterexamples fail against the original component.

### Root cause
Final state publication did not repeat the deadline check after metadata work;
a copied manual collector needed its own final path rebind.

### Fix applied
Fresh telemetry2 rechecks clock/frozen state immediately before both ordinary
writes and keeps caller-local unavailable cancellation tails distinct from worker
results. Rebind the visible group after final mount/boot/self-path IO with the
original descriptor still held. Original component/unfavorable review preserved.

### Prevention
The three exact regressions and four cancellation/expiry controls pass independent
review. Coherent source passes312 finite cases; the fresh actual full-4 run reports
complete same-call metadata without errors. This does not recover full-3's substep.

---

## ERROR-158 — Final mount read could outlive the visible group binding

**Date:** 2026-10-15
**Severity:** high
**Status:** fixed (shared source; actual qualification pending)
**Found by:** independent kernel review using finite ordinary directories
**Affected files:** builder/contained_kernel.py and its unit regression

### What happened
A finite second mount-observation callback renamed/recreated the expected group
path after its visible check. The collector returned the original held inode even
though the current path named a different inode. The exact repro failed with
DID NOT RAISE against the first held reader component.

### Root cause
The held FD check after final mount IO established descriptor continuity without
rebinding the visible expected path after that IO.

### Fix applied
The fresh V2 component reopens the visible group after final mount/boot/self-path
reads and compares device/inode/UID and FD mount ID before publishing facts.
Preserve the original source80541063 and unfavorable review9d173c71.

### Prevention
Keep the original real temporary-directory replacement regression. The same
private manual collector interval is separately tracked during its integration;
a shared producer fix alone does not repair another collector's ordering.

---

## ERROR-157 — Mount metadata exceeded the generic kernel-file cap

**Date:** 2026-10-15
**Severity:** high
**Status:** fixed (source; actual qualification pending)
**Found by:** read-only postfailure compatibility check
**Affected files:** shared mount reader, exact parent profiles and execution method

### What happened
The current mount table contains5,142 bytes and the old4,096-byte generic read
raises ValueError. This is a reproducible current compatibility condition; it does
not identify the unretained original failing substep of ERROR-156.

### Root cause
A complete mount table used the same small bound as individual numeric kernel
files. Increasing that generic bound would change unrelated reads and old method
identities without describing those changes explicitly.

### Fix applied
Introduce one fixed-name64KiB reader, same-call complete/overflow/unavailable
metadata, namespace/root/group binding and exact new current261/262 profiles.
Keep all other kernel bounds and historical identities intact; V8 stays disabled.

### Prevention
Real finite fixtures cover5,142,65,536 and65,537-byte boundaries, malformed and
ambiguous tables, namespace/path replacement, immutable read metadata, historical
readability and rejection of historical tuples at fresh execution boundaries.

---

## ERROR-156 — Actual full importer stopped before parent promotion

**Date:** 2026-10-15
**Severity:** high
**Status:** open
**Found by:** Root actual manual full-CAS attempt and independent file audit
**Affected files:** private parent observer and shared contained_kernel mount reader

### What happened
The first scoped attempt exits 1 in 0.917s before container launch. All five saved
D-Bus queries succeed with expected unit properties, but the kernel/controller/
parent interval raises ValueError without retaining its exact step. Cleanup
separately denies an absent immutable container seal; it preserves the first error.

### Root cause
The original failing substage remains unknown. A later read-only current-host
probe reproduces mountinfo 5,142 B exceeding the shared reader's 4,096-byte cap.
That is a concrete compatibility problem, not retrospective proof of the old step.

### Fix applied
No predicate change or retry. Preserve source/packet/full-3 output, verify absent
unit/cgroup and unchanged 21-container baseline, and plan versioned bounded mount
metadata reads plus immutable parent-step diagnostics before a fresh attempt.

### Prevention
Retain bounded first-step kernel diagnostics and first-failure phase. Exercise
metadata readers against realistic host sizes while preserving finite bounds,
source/version identities and historical failed qualification outcomes.

---

## ERROR-155 — Known capture failure could precede the first barrier release

**Date:** 2026-10-15
**Severity:** high
**Status:** fixed (finite source)
**Found by:** independent coherent importer review
**Affected files:** private host_bootstrap_operator.py and cas_lifecycle.py

### What happened
A capture error arriving during the initial core read still allowed the first
release file to be created. A supplied-IO coordinator regression reproduced it.

### Root cause
The earlier check preceded intervening awaits; the physical writer had no capture check.

### Fix applied
Check after the initial read and pass the same capture object mandatorily to
both barrier workers. Check its current first error after directory FD IO,
immediately before O_EXCL creation. The coordinator and both finite FD cases pass.
The first 1,640-file source remains preserved; actual preparation is still pending.

### Prevention
Carry the original failure owner to the effect boundary; an earlier boolean or
report cannot stand in for its current state.

---

## ERROR-154 — Declared clean launch environment could not import the backend

**Date:** 2026-10-15
**Severity:** high
**Status:** fixed (finite source)
**Found by:** Root passive clean-entry preflight
**Affected files:** private host_bootstrap_operator.py

### What happened
The 339-check candidate failed standalone --help with ModuleNotFoundError:nexus.
No scope or container started. Pytest's supplied backend path masked this entry problem.

### Root cause
Helper imports preceded the existing facts module's pinned backend bootstrap.

### Fix applied
A fresh archive imports facts first and preserves that order explicitly. The
subprocess regression uses exactly the declared launch environment and passes;
the original failure and all 1,640 original source files remain intact.

### Prevention
Exercise the CLI entry under its actual declared environment and an unrelated
working directory before a launch; in-process tests do not establish that ABI.

---

## ERROR-153 — Inventory text replacement removed the profile declaration

**Date:** 2026-10-15
**Severity:** medium
**Status:** fixed (finite source)
**Found by:** Root collection during private full-CAS integration
**Affected files:** private host_bootstrap_profiles.py

### What happened
A coarse replacement of source-inventory constants also removed ProfilePins.
Collection raised ImportError before any actual recipe was frozen or executed.

### Root cause
The replacement endpoint was the later fixed_inputs function, beyond the class.

### Fix applied
Restore the held profile and replace only the two AST assignment spans. Combined
source/profile regressions and configured strict24 pass; original failure logs remain.

### Prevention
Check that declarations survive mechanical namespace/inventory forwarding before
freezing source; use syntax spans for adjacent declarations.

---

## ERROR-152 — Monitor could reset or skip the original first sampling slot

**Date:** 2026-10-15
**Severity:** high
**Status:** fixed (finite source)
**Found by:** independent monitor source review
**Affected files:** private cas_monitor.py

### What happened
Delayed attachment or dispatch reset the first slot; an initial repair still
accepted a later wait(0) before dispatch with no sample after the missed slot.

### Root cause
The deadline was anchored inside the task, and wait.done preceded its check.

### Fix applied
Anchor to the original initial sample before task creation and check the slot
before wait.done. Three meaningful regressions and independent review pass.

### Prevention
A later successful wait cannot rescue a missed observation window. Keep periodic
named-process observations distinct from complete-tree barrier evidence.

---

## ERROR-151 — Artifact facts could describe replaced or changed stored output

**Date:** 2026-10-15
**Severity:** high
**Status:** fixed (finite source)
**Found by:** independent finite artifact review
**Affected files:** private cas_artifact.py

### What happened
Finite fixtures replaced the extracted root, changed final ledger permissions,
and rewrote equal-length stored bytes before or immediately after readback.
Earlier candidates returned the original facts despite these changes.

### Root cause
The final named root lacked a descriptor binding, and complete stored-byte hashes
were not bracketed by final FD/named metadata checks.

### Fix applied
Retain the root descriptor through final checks; read back the stored ledger and
compare metadata before/after hashing, including mode/owner/links/mtime/ctime.
Apply final archive metadata checks after its hash.14 tests and peer review pass;
all failed candidates are preserved. Actual full-CAS execution remains pending.

### Prevention
Hash actual stored bytes with stable descriptor/path observations. This does not
provide atomic protection from hostile same-UID writers or power-loss durability.

---

## ERROR-150 — Initial observation conflated lifetime and per-call read deadline

**Date:** 2026-10-15
**Severity:** high
**Status:** fixed (finite source)
**Found by:** Root full-CAS driver integration
**Affected files:** private cas_inputs.py and host_bootstrap_operator.py

### What happened
The new driver passed the long parent lifetime to inner input reads while its
owned await used a shorter deadline. A finite supplied-clock case accepted reads
past that shorter end. The earlier actual30-second input check is unchanged.

### Root cause
The initial observation API used one end for both lifetime and individual IO.

### Fix applied
Add an explicit shorter IO end; forward it to every read while retaining the
original observation lifetime. Short-end denial and lifetime-preservation tests pass.

### Prevention
Separate these bounds at initial observation as well as later revalidation;
outer await timeout alone cannot stop a synchronous filesystem worker.

---

## ERROR-149 — Canonical child defaults raised before runtime applied finite limits

**Date:** 2026-10-15
**Severity:** medium
**Status:** fixed for pending observation; older actual callsite remains unknown
**Found by:** real descriptor tests after V4 investigation
**Affected files:** private readiness helper/test and fresh source namespace

Three original helper tests reproduce ValueError on canonical child memory/pids
max and CPU max100000. Fresh V5 returns unready for those exact defaults while
rechecking identities; only repeated exact finite caps permit the first query.
Root max/malformed/unknown cases still deny. Immutable bounded read-step evidence
retains the original exception.122 focused/static checks and independent review
pass. Actual V5 reaches readiness/live trees and cleans up, but still rejects
CLI255/inspect-1 under its unchanged137 criterion. Do not infer V4's exact cause
or relabel the preserved timeout failure as completed work.

---

## ERROR-148 — Passive startup observation failed before readiness; cleanup unresolved

**Date:** 2026-10-15
**Severity:** medium
**Status:** open; exact failing read is unknown
**Found by:** actual diagnostic V4
**Affected files:** private HostBootstrap readiness/cleanup boundary

The first passive observation records controller-at-root/two direct processes/
empty subtree; the next raises generic ValueError. Cleanup kills/reaps only the
owned CLI and seals its exact created container, but removal fails. Preserve that
container and21-row inventory; original20 rows remain unchanged. No barrier or
PID-tree proof exists. A child interface's canonical default max is a supported
pending-state candidate that the strict numeric parser rejects; it is not uniquely
proven as this actual callsite. Add bounded read-step evidence and a child-only
pending classification without weakening parent caps or allowing readiness.

See [actual diagnostic evidence](company-system/HOST_TIMEOUT_DIAGNOSTIC_CHECKPOINT_2026-10-15.md).

---

## ERROR-147 — Special pnpm receipt row omitted its semantic hash join

**Date:** 2026-10-15
**Severity:** medium
**Status:** fixed in fresh input source; full import remains held
**Found by:** independent Root input-helper review
**Affected files:** private cas_inputs.py and focused tests

Actual pnpm archives were checked against configured hashes and integrity, but
the receipt's special pnpm SHA was not compared with that configured SHA. A
negative repins the receipt after changing only that row and reproduces acceptance.
Fresh V2 adds the missing receipt/spec equality; actual byte/SHA/SRI checks remain.
35 focused checks, strict/Ruff and actual read-only full input revalidation pass;
independent file review is favorable. Preserve V1; a pinned receipt still needs
semantic joins for every record. No runtime or import authority is granted.

See [input evidence](company-system/CAS_INPUT_CHECKPOINT_2026-10-15.md).

---

## ERROR-146 — Native startup cannot open the payload cgroup pids.max

**Date:** 2026-10-15
**Severity:** medium
**Status:** open; failed source and namespace preserved
**Found by:** actual diagnostic V3
**Affected files:** private rootless HostBootstrap/controller setup

CLI127 and retained stderr/state identify runc cgroup configuration failing on
payload pids.max with ENOENT. State remains created with unset timestamps/PIDs0;
its exit_code0 is not success. Current ancestors expose/enable cpu/memory/pids,
but the removed parent subtree state is unavailable. Underlying setup/race cause
is unproven. Research exact installed runtime semantics before a fresh reviewed
remedy; preserve caps and require actual enforcement evidence. Cleanup passes.

See [diagnostic evidence](company-system/HOST_TIMEOUT_DIAGNOSTIC_CHECKPOINT_2026-10-15.md).

---

## ERROR-145 — Early startup failure bypassed stderr and extended-state capture

**Date:** 2026-10-15
**Severity:** medium
**Status:** fixed for diagnostic observability; startup qualification remains open
**Found by:** actual diagnostic V2
**Affected files:** private HostBootstrap diagnostic/operator tests

The early seal failure retained CLI127 but never entered ready/terminal capture,
leaving stderr unread and extended state absent. Fresh V3 eagerly owns one bounded
stderr task and snapshots completed early-failure facts plus fixed sealed-ID state
before freeze/cleanup.82 focused tests, configured static checks and source review
pass. Its fresh actual failure preserves451 stderr bytes and the created-state
cgroup error within the original deadline. Old evidence is not backfilled.

---

## ERROR-144 — Capture constructor could orphan tasks after a fallible initial mark

**Date:** 2026-10-15
**Severity:** medium
**Status:** fixed before fresh execution
**Found by:** independent diagnostic V1 source review
**Affected files:** private HostBootstrap RuntimeCapture constructor/test

An initial stderr mark could throw after wait/export tasks were created but before
the caller retained their handles. Fresh V2 performs all initial fallible marks
before creating tasks. A semantic failure case verifies zero newly created tasks;
78 focused tests and independent review pass. V1 remains preserved and unexecuted.

---

## ERROR-143 — Tiny timeout outcome conflicts with its frozen terminal expectation

**Date:** 2026-10-15
**Severity:** medium
**Status:** open; preserved failure, no retry
**Found by:** actual separate fresh262 TIMEOUT2 probe
**Affected files:** private HostBootstrap terminal contract/diagnostics

The16.57s probe records stopped exit_code=-1/non-OOM three times, conflicting with
expected137. Validation fails; exact-ID cleanup and runtime reaping succeed.
Original query/PID/stream evidence remains, but runtime CLI exit/stderr/launch/
read-end were not saved, so complete cause is unknown. Later absence checks are
corroboration, not original timer/cause proof. Preserve the failed source, namespace
and expectation. Research installed engine semantics and freeze a fresh bounded
diagnostic plan before another run; never convert -1 into successful work.

See [the current host checkpoint](company-system/HOST_BOOTSTRAP_262_CHECKPOINT_2026-10-15.md).

---

## ERROR-142 — Private image inspection repeated the Go field/JSON tag mismatch

**Date:** 2026-10-15
**Severity:** medium
**Status:** fixed for the fresh normal bootstrap; full qualification remains open
**Found by:** actual first262 normal probe
**Affected files:** private host_bootstrap_facts.py image template/test

Parent/kernel checks pass, then read-only image inspection exits125 on json.Id.
The earlier ERROR104 correction covered native container templates, but this
private image caller retained the same mistake. An actual read-only json.ID query
returns the exact image/platform. Preserve the failed run; a fresh source and
namespace add an exact-argv red, correct only the field and pass54 mock checks
plus actual normal execution/cleanup. Check every fixed read-only engine template
against the configured store before a new bounded launch. Timeout remains separate.

---

## ERROR-141 — Model-footprint exclusion omitted canonical artifact and original intent time

**Date:** 2026-10-15
**Severity:** high
**Status:** fixed before source integration
**Found by:** independent P/C V2 boundary review
**Affected files:** cycle artifact issued/model issuance facts and metadata tests

The first mixed model/tool repair accepted one model receipt without checking its
canonical artifact ID/revision, or the original approval's expiry at intent time.
The frozen V2 and unfavorable review remain. Four real-helper semantic reds cover
foreign artifact ID, wrong revision and intent at/after expiry. A cohesive metadata
helper binds UUID5(action,request), model-result-envelope-v1 and intent<original
expiry; valid later receipts remain accepted.254 focused/4,165 full units and
configured static checks pass; independent V3 review is favorable. No model body,
current-owner reauthorization or new authority is introduced.

---

## ERROR-140 — Publication counted a legitimate model request as duplicate tool issuance

**Date:** 2026-10-15
**Severity:** high
**Status:** fixed before source integration
**Found by:** independent P/C V1 boundary review
**Affected files:** cycle artifact issued facts and verifier tests

P/C reserve one model and one tool attempt. Counting all intents as publication
duplicates rejected a valid succeeded model followed by its tool publication.
Two real-helper P/C reds reproduced this. Keep an unfiltered bounded candidate
read; recognize at most one fully bound succeeded/reconciled canonical native
model footprint with exact permanent counters. Every other candidate remains
counted; failed, unknown, pending and tool-as-model rows deny. V1/V2 failures and
reviews are preserved; V3 passes the coherent regression and independent review.

See [the publication checkpoint](company-system/CYCLE_PUBLICATION_SOURCE_CHECKPOINT_2026-10-15.md).

---

## ERROR-139 — Current CSV fixture still expected the previous company head

**Date:** 2026-10-15
**Severity:** medium
**Status:** fixed in source; no native fixture retry
**Found by:** Root exact-source full regression after company016 addition
**Affected files:** tests/csv_native_scope.py and its scope unit tests

The first candidate had one failure and3,843 passes: the unchanged current-head
assertion compared016 with the fixture's015 expectation. The frozen historical
015 run cannot be repinned or replayed under that old database/root identity.

Version the current fixture to016 and fresh exact v2 database/root names. Preserve
the head assertion, immutable public-input lineage and all old source/DB/proof.
Three real old-namespace denial reds precede the fix;19 focused and3,847 full units
pass. Future actual CSV setup needs a new source/operator packet and runtime pins.

---

## ERROR-138 — Generated HTML contracts lacked matching persistent media support

**Date:** 2026-10-15
**Severity:** medium
**Status:** fixed and qualified on fresh local company databases
**Found by:** P/C source review and Root ORM constraint inspection
**Affected files:** Brain source policy/record/ORM, company016 and native event capability

The compiler emits HTML, but contracts and the database media CHECK allowed only
plain text, Markdown and JSON. A type-only extension would still fail persistence.
Adding016 also exposed the native-event capability's exact015 version guard.

Keep truthful text/html and require derived origin/identity; add company016 with
an equivalent named CHECK and preserve same-company deferred derivation FKs.
Recognize exact015/016 event profiles with full physical-column checks. Normal
downgrade refuses retained HTML without deleting evidence. Source reds, configured
static13,3,847 full units and12 real restricted-PG/profile checks pass; independent
audits pass. Original008/legacy history and failed first regression remain intact.

See [the scoped checkpoint](company-system/DERIVED_HTML_SCHEMA_CHECKPOINT_2026-10-15.md).
No production migration or native P/C execution follows from this qualification.

---

## ERROR-137 — Generic managed tools could select the model-request attempt slice

**Date:** 2026-10-15
**Severity:** high
**Status:** fixed (managed validator)
**Found by:** Codex during P/C intent-boundary integration
**Affected files:** company/management/plan_support.py and existing cycle catalog tests

### What happened
A valid generic artifact-write proposal passed the real validate_plan_action with
kind=model_requests. The semantic reproduction failed1.13s (DID NOT RAISE); no actual
SQL counter mutation is claimed by that pure test.

### Root cause
The model branch enforced its request kind, but the generic non-model tool branch
had no reciprocal tool-attempt requirement. Specialized E/N checks did not cover it.

### Fix applied
After the unchanged model.request.v1 return, require tool_attempts for managed
tools. Existing EffectStore ordering performs this validation before hold movement
or attempt reservation.9 focused/3814 full units, configured static2 and independent
file review pass; legitimate model-request behavior remains covered.

### Prevention
Validate effect category alongside exact tool/version/resource and permanent quota.
See [the scoped checkpoint](company-system/MANAGED_ATTEMPT_KIND_CHECKPOINT_2026-10-15.md).

---

## ERROR-136 — Current user manager differs from the qualified bootstrap profile

**Date:** 2026-10-15
**Severity:** medium
**Status:** mitigated (exact262 source added; current full-method qualification pending)
**Found by:** Codex during the first actual tiny HostBootstrap run
**Affected files:** private bootstrap source; native user-parent compatibility contract

### What happened
The normal probe stopped1.26s at UserManagerObservation validation before any
container. Actual bus replies reportUID1000/systemd262-1; the frozen profile
accepts261.2-1. Only two complete/reaped queries were captured, with no parent,
container seal, runtime PID or payload evidence.

### Root cause
Historical profile compatibility was not reconciled against the current daemon
version in the initial read-only namespace preflight. The actual version guard
correctly refused the unsupported context. The time/cause of host change is unknown.

### Current action
Preserve failed source/root/packet/logs; no original retry or timeout run. Fresh
postchecks show unit/cgroup/name absent and existing20-container inventory unchanged.
The fresh raw diagnostic now passes0.49s with all five complete/reaped replies,
actual262-1/kernel caps/ENODATA61 and independent file audit. This supports the
closed-profile source extension; current native identity, timeout and execution
qualification remain open. See the
[raw checkpoint](company-system/HOST_PARENT_262_RAW_CHECKPOINT_2026-10-15.md).

### Prevention
Read current daemon UID/version against the declared supported profile before
creating a scope. Do not fabricate a version or reuse historical execution proof.
See [the failure checkpoint](company-system/HOST_BOOTSTRAP_TINY_FAILED_CHECKPOINT_2026-10-15.md).

---

## ERROR-135 — Retained engineering proof did not reread its private sidecars

**Date:** 2026-10-15
**Severity:** high
**Status:** fixed before source integration
**Found by:** independent P/C milestone reviewer
**Affected files:** engineering_prerequisite_reader.py and its existing reader tests

### What happened
The first candidate's final revalidate_locked checked actual public result refs,
body integrity and original windows, but sidecars were reread only during material
load. Later missing/corrupt private evidence could pass that final boundary.

### Root cause
Result-reference integrity was mistakenly treated as sufficient for subsequent
interpretation of the retained full result. A green3,809-unit run missed this path.

### Fix applied
Preserve V1 and its unfavorable review. Fresh V2 invokes existing
require_result_containment for each result during final revalidation. Four real
local sidecar negatives first reached the later-body sentinel (2.35s), then deny
before it. Upstream qualification/SQL delivery remain explicit mocks.319 focused,
3,813 full units, static13 and independent V2 review pass; no actual E claim.

### Prevention
Every v2 result interpretation must reread original private sidecar bytes, including
retained/supplied proofs. Public hashes and cached prior reads do not replace it.

---

## ERROR-134 — Same-path containment store replacement escaped composition checks

**Date:** 2026-10-15
**Severity:** medium
**Status:** fixed before first source freeze
**Found by:** Codex during P/C source composition review
**Affected files:** cycle_artifacts/native_contracts.py and protection tests

### What happened
The draft fingerprint retained the containment root path and method hash but omitted
the store object's identity. A fresh same-path store reset its pinned root identity
without changing that fingerprint. The retained regression failed1.90s.

### Root cause
A semantic path fingerprint did not preserve the concrete evidence-store instance.

### Fix applied
Retain the original store object in the composition identity tuple, including the
legitimate legacyNone case. An actual configured-reader/store replacement regression
now denies. Root3813 units and configured static13 pass with the final package.

### Prevention
Retain concrete IO composition across awaits as well as its configured values.
Do not treat a fresh same-path adapter as the original pinned store.

---

## ERROR-133 — Draft prerequisite accepted succeeded issuance with zero tool usage

**Date:** 2026-10-15
**Severity:** medium
**Status:** fixed before first source freeze
**Found by:** author during P/C component self-review
**Affected files:** engineering_prerequisite_facts.py and its facts tests

### What happened
Actual-shaped serialized succeeded action/intent/attempt rows were accepted even
when the E/EV work counter reported zero issued tools. The regression failed1.51s.

### Root cause
The first issuance check compared native records but omitted their permanent work
counter conservation requirement.

### Fix applied
Require strict-int tool limit/used/delegated=(1,1,0) for both issued E/EV works.
Retain the semantic red and counter denials; final319 focused/3813 full units pass.
The test is mocked native-row delivery, not actual accepted E/EV qualification.

### Prevention
Match native issuance to permanent counters, including strict numeric types, rather
than accepting a plausible receipt graph alone.

---

## ERROR-132 — Release regression included an unfinished untracked local probe

**Date:** 2026-10-15
**Severity:** low
**Status:** fixed (source selection; local probe preserved)
**Found by:** Codex during neutral family-reader integration
**Affected files:** test invocation/source snapshot; no change to the local probe

### What happened
The initial full primary-checkout run also collected preserved untracked
`test_strategy_publication_pg_scope.py`. Its empty-URL case failed:1 failed,
3,771 passed in108.32s. The three changed release files were not that probe.

### Root cause
A directory-wide test invocation included unfinished local work outside the
reviewed release-source closure, despite that work being visible in git status.

### Fix applied
Preserve the failed log and all four original untracked files. Build a fresh exact
snapshot of committed backend plus only the three reviewed seam files;3,758 units
pass80.76s. Static checks and264 relevant compatibility tests also pass. No local
probe behavior or production validator was changed to obtain the release result.

### Prevention
Reconcile test discovery with the declared release source when local unfinished
probes coexist. Report the local failure and exact-source result separately.

---

## ERROR-131 — Public dependency stage did not preserve requested private mode

**Date:** 2026-10-15
**Severity:** low
**Status:** fixed (operator location; strict guard retained)
**Found by:** Codex during actual public dependency restoration
**Affected files:** private public-download operator packet; no backend change

### What happened
The actual stage mkdir requested0700 on/mnt/data but produced0755. The initializer
stopped0.606s before its first fetch and before a download receipt. The empty failed
stage and all source/release/logs remain retained.

### Root cause
Requested modes were treated as a sufficient placement assumption on this FUSE
volume. The matching skill already recorded this mount-specific behavior for
secret staging; that lesson was not consulted at the new artifact boundary.

### Fix applied
A fresh same-parent Linux-filesystem probe proved directory0700/file0600. A NEW
path-only packet then completed517packages+pnpm in46.04s. Independent audit verifies
all520files/two directories, actual modes/UID/link counts and integrity. Old packet
was not resumed; the private-mode guard and other limits are unchanged.

### Prevention
The project skill now routes new cache/staging-root selection to the existing
private-permissions lesson. Recheck actual filesystem behavior; requested mkdir or
chmod is insufficient. Later independent reuse of this routing change is unknown.
See [the dependency checkpoint](company-system/PUBLIC_RUNTIME_DEPENDENCY_STAGE_2026-10-15.md).

---

## ERROR-130 — Literal credential-free download policy allowed server cookies

**Date:** 2026-10-15
**Severity:** medium
**Status:** fixed (private operator)
**Found by:** independent file reviewer before any real download
**Affected files:** private public_download_operator.py and its mock tests

### What happened
HTTPX's persistent client could carry a server Set-Cookie into a later request,
violating the private operator's literal credentials=none policy.

### Root cause
trust_env=False and absent supplied Authorization do not disable the cookie jar.
The initial mock cases did not inspect subsequent actual transport headers.

### Fix applied
A request hook on both actual clients removes Cookie, Authorization and
Proxy-Authorization after merge/auth and before each transport request, including
manual redirects. Five real MockTransport regressions first failed, then all28
passed. Independent source review verifies pinned HTTPX0.28.1 ordering. Production
APIs that support optional authenticated downloads were not changed.

### Prevention
Test transport-boundary headers across redirects and subsequent objects when the
policy is literal credential-free. Recheck ordering on client/version changes.
Actual download success is not independent wire-header capture evidence.

---

## ERROR-129 — Runtime preflight inspected Docker before the configured Podman store

**Date:** 2026-10-15
**Severity:** low (operator observation)
**Status:** fixed by exact configured-engine read-only inspection
**Found by:** real Node-v4 runtime preflight
**Affected files:** private preflight receipt; no production change

Docker default reported the pinned image absent. The runtime descriptor names
/usr/bin/podman --remote=false, whose separate store contains the exact declared
image ID, digest and amd64/Linux platform. The initial observation could not
support a claim about that configured store; the user-facing statement was corrected.

Use the descriptor's binary/remote mode/user and exact image ref/ID before any
recovery operation. Do not print Env/Config or credential data. Receipt
real-node-v4-runtime-preflight-1.json cc8e507c records both scoped observations.
Missing host CAS/tool/pnpm paths remain a separate verified prerequisite.

---

## ERROR-128 — Fixture compared PostgreSQL internal catalog char bytes with text

**Date:** 2026-10-15
**Severity:** low (fixture guard; no production reader change)
**Status:** fixed in fresh v2; complete reader SQL passes28.18s
**Found by:** first actual reader SQL recipe
**Affected files:** private tail and final catalog inventory projections

Four cases completed before the tail guard failed31.80s, before mutation. Pinned
asyncpg decoded pg_trigger.tgenabled as bytes4f, while the unchanged strict guard
required textO. Root's actual read-only catalog probe proved native comparison
false and ::text comparison true, with every other owner/trigger/RLS field correct.

Fresh v2 changed only both SQL projections to ::text and its closed fixture
identities. No predicate, privilege, time limit, fault or production validation
was relaxed. The first source/run/database and its original five blobs remain.
Actual v2 app P0001 before/after the isolated fault and paired full-tail denial
now pass; see ENGINEERING_COMPLETE_BODIES_PG_CHECKPOINT_2026-10-15.md.

---

## ERROR-127 — Private engineering consumer rejected complete results above one page

**Date:** 2026-10-15
**Severity:** medium
**Status:** fixed; bounded five-case actual reader SQL v2 qualified
**Found by:** real StockFlow preparation and bounded reader reproduction
**Affected files:** engineering_inputs.py, engineering_acceptance.py, engineering_bodies.py

The metadata contract allowed complete results above16KiB, but the private reader
loaded one public page and rejected honest has_more. A valid full result first
failed that original condition1.33s. The new private loader assembles sequential
native pages, retains the first metadata/freshness and checks full length/SHA/UTF8.
Both consumers pair slice and full-reference revalidation so a changed stored tail
cannot hide behind a matching prefix. Public/proof/result limits stay unchanged.

77focused, Root3,753unit/67.03s and strict/lint/format6 pass; independent source
review is favorable. Actual restricted READ/revocation/expiry/tail integrity and
real timing remain separate. See the complete engineering body source checkpoint.

---

## ERROR-126 — SQL fixture diagnostic used Python validation for JSON parameters

**Date:** 2026-10-15
**Severity:** low (fixture failure; no sender effect issued)
**Status:** fixed in fresh v2; actual direct SQL passes189.23s, SDK/live gates remain
**Found by:** first actual B2b SQL recipe
**Affected files:** private mixed_sender_pg_publication.py diagnostic

After public first-lineage/head2 and native notification authorization/enqueue/
claim, canonical_spec_hash called strict model_validate on ActionProposal.parameters
created with mode=json. Five nested UUID strings and two list fields produced
seven validation errors. The recipe stopped1FAILED/90.64s before generic begin,
send, second company, rollback or history. Source/run/database and original N
held reservation/lease remain preserved, with no renewal/refund or resumption.

A fresh v2 uses the exact strict JSON validation entry point and an actual
make_spec→serialized ActionProposal.parameters regression. No production validator
or original time recipe is relaxed. Earlier preflight findings also remain saved:
the history observer's nonexistent method was reproduced and corrected, and exact
all-table conservation now surrounds recovery/release. These source corrections
are not a successful mixed SQL qualification. Root terminal and independent file
audit record the failed state and shutdown app0.

Fresh v2 retained the same seven-error actual-producer red, then57pure/strict4
checks passed without validator relaxation. Its complete SQL recipe passed189.23s;
see MIXED_SENDER_B2B_PG_CHECKPOINT_2026-10-15.md. The failed original stays preserved.

---

## ERROR-125 — Mixed sender needed complete final composition and history pins

**Date:** 2026-10-15
**Severity:** high (source hazards; mixed runtime was still closed)
**Status:** fixed in source; direct SQL v2 qualified, SDK/live gates remain
**Found by:** tests-first implementation and independent source review
**Affected files:** mixed_notification_history.py, managed_effects.py, mixed sender boundaries

Initial history comparison omitted actual ExecutionWork actor/workspace (absent
from registration JSON) and accepted a reset issued tool counter. Six crossed-row
tests and one counter test first failed with DID NOT RAISE; explicit row identity
and consumed-counter checks now deny them.

The initial shape check bound preparation only before later awaits. Final validation
now reruns the concrete shape against the original catalog/work/action/preparation.
A further probe replaced the check itself: branching on its current type skipped
mixed checks. Final validation now branches on original bound type and rejects
replacement. All seven drift cases pass after retained failing reproductions.

Fresh generic begin also needed a mandatory mixed native check before mutations;
the old optional/no-op path had three reproduced failures. Actual begin now denies
them and preserves existing unknown-intent early return and full native validation.
Root3,715unit/84.69s and strict/lint/format23 pass. No real mixed sender effect was
issued by these source/mock reproductions; SQL/SDK/recovery remain separate gates.

---

## ERROR-124 — Fixture metadata suffix did not match PostgreSQL's dotted token

**Date:** 2026-10-15
**Severity:** low
**Status:** fixed in fresh v2 fixture; original package preserved unexecuted
**Found by:** independent preflight source review and Root read-only PostgreSQL probe
**Affected files:** private selected_builder_pg_snapshot.py fixture

The fixture searched selectedbuildermetadata, while the actual metadata contained
only stockflow.synthetic.selectedbuildermetadata. PostgreSQL17.6 simple text search
indexes that dotted symbol as one token. Root observed suffix=false/full-symbol=true
before any fixture database/run was created; pure checks had not qualified retrieval.

A fresh v2 source/run/DB/company namespace changes the query and mapping to the
complete symbol. Its actual metadata bytes/query pass a second read-only FTS probe,
then the real two-company READ/guard recipe passes163.45s. No production retriever,
parser, indexing policy or accepted source bytes were changed. The first frozen
source/packet stays unchanged and unexecuted. This was a preflight fixture finding,
not an actual fixture SQL failure. Preserve exact query/serialized-byte probes for
future retrieval-dependent qualification.

---

## ERROR-123 — Credential wrapping would discard the selected source guard

**Date:** 2026-10-15
**Severity:** high (integration hazard; mixed execution was still closed)
**Status:** fixed for source composition; actual selected SQL/runtime pending
**Found by:** B2a source review and intentional original-context reproduction
**Affected files:** engineering_worker_context.py, effect_store.py, selected builder modules

The original context always constructed EngineeringCredentialSourceGuard from the
resolver result. That wrapper copies base fields and loses specialized overrides.
Returning a selected resolver subclass alone therefore would not install selected
Strategy validation. EffectStore.begin also accepts an optional before-intent check;
opening ancestry alone would not make that check mandatory. Existing closed mixed
ancestry prevented this from being an observed active bypass.

Context now requires concrete selected configuration before acquiring a lease and
constructs the final concrete selected guard. Fresh mixed E/EV begin requires the
exact bound selected-guard/contained-parent composite before any native mutation.
Known issued history keeps its original early return. No ancestry opening is shipped
separately from these gates.

The retained original16c context reproduction fails both current regressions in
0.40s (missing service accepted; final guard lost). The combined implementation
passes3,633unit/54.05s and configured strict/lint/format25. Actual native SQL/parent
qualification remains separate; no real effect was issued by this reproduction.

Independent review also nominated composition drift after disclosure during later
parent/revalidation/flush awaits. The final synchronous selected callback now checks
factory/catalog/input-reader identity again before its time checks. Three retained
tests first failed with DID NOT RAISE, then passed with this correction; the focused
60-test context/guard/intent group passes3.69s. Final combined qualification is
recorded in the B2a source checkpoint.

The direct result-disclosure path also needed this check after its own last clock
await. Centralizing composition validation in the shared selected final check closes
both paths. The nominated drift probe first failed with DID NOT RAISE1.28s; the
corrected61-test group passes3.84s. Earlier probe import/argument fixture errors
are retained separately and are not evidence of the production gap.

---

## ERROR-122 — B1 SQL packet omitted the Unix-socket URL user separator

**Date:** 2026-10-15
**Severity:** low
**Status:** fixed (fresh v2 packet qualification; failed fixture preserved)
**Found by:** first actual B1 SQL qualification
**Affected files:** private `SETUP_PACKET_1.json` fixture

The packet supplied `postgresql+asyncpg://santapong/database?...` instead of the
reviewed socket form with `santapong@/database`. SQLAlchemy interpreted the former
as a host rather than the required username. The strict fixture guard correctly
denied before constructing an engine. Collection with an empty URL did not validate
the actual packet's future URL, and review missed this literal difference.

Root87641 failed once in1.97s; independent SQL confirms the created database has
zero public tables and zero application backends. No migration, company, source,
credential or operative action was created. Preserve the original source/run/empty
DB; a fresh reviewed v2 packet must derive its URL from the typed URL constructor
and validate that actual packet value in check-only mode before execution.
No production URL guard is weakened. Root failed receipt599c3312 is authoritative.

The fresh v2 packet derives its URI through SQLAlchemy URL.create and passes its
actual frozen environment value through the same pre-engine guard in mandatory
check-only and a separate file-only test. Root confirmed that test1.38s; the actual
two-company transition/rollback recipe then passed97.41s. All first-run bytes and
the empty database remain unchanged.

---

## ERROR-121 — Owner SQL fixture assumed every nested blob directory was 0700

**Date:** 2026-10-15
**Severity:** low
**Status:** fixed (fresh v2 fixture audit; failed v1 run preserved)
**Found by:** first actual owner-proof SQL run
**Affected files:** private `strategy_owner_pg_ledger.py` fixture

The first run completed its positive company's native B/S/C publication, receipts
and acceptance, then failed before the owner reader at the file-audit assumption
that every nested directory was mode0700. The actual protected root and artifact
directories are0700, immutable files0400, and the intermediate company directory
is0775. `Path.mkdir(parents=True, mode=0700)` applies that mode to the final directory;
intermediate parents use the process umask. The outer0700 boundary remains intact.

Root91036 failed once in18.42s. Fresh SQL confirms one company, three work rows,
two original intents/attempts, one acceptance/proof and no app backends. No owner
read or later case ran. Preserve DB/tree/source/TTLs/holds; do not chmod or retry
the original. A corrected fixture must audit actual ownership/type, protected root,
immutable file modes and unchanged directory metadata in a fresh namespace.
Production storage behavior is not changed by this finding.

The fresh v2 inventory records actual directory device/inode/UID/mode and checks
all five files against actual source/publication/check refs. An actual BlobStore
umask0002 test retained the original failure, then four metadata checks passed;
25 focused/static16/check-only1522 passed. The new four-case SQL recipe passed
90.62s, with unchanged ledgers/blobs and independent terminal auditda7c43a7.

Root failed-terminal receipt SHA256
`2c3637e3792641fe851cb4198c2d8b0d0a4f0a95c6fcf56bf028edaaa6e92fcd`
is saved in the private owner-proof run directory. Actual owner READ/expiry proof
remains unqualified; a new reviewed fixture is required.

---

## ERROR-120 — New window narrowed the legacy aggregate resource set

**Date:** 2026-10-15
**Severity:** medium
**Status:** fixed (dormant source/mock capture)
**Found by:** independent admission-window source review
**Affected files:** `management/plan_admission_metadata.py`

The first capture derived aggregate expiry resources from used child grant pairs.
Legacy final validation includes every declared charter's catalog resources, so an
unused charter's expiring grant was omitted. A retained real ordinary four-child,
five-charter mock-SQL case failed DID NOT RAISE in 1.35s. The aggregate helper now
derives the exact legacy union internally; explicit qualified grant/source snapshots
remain restricted to used resources. Predicate-faithful fake SQL covers the query.

Nineteen focused, 226 compatibility and Root3,253unit/54.77s checks pass, with strict
types/lint/format12 and independent review. Current full mixed admission already
rejects the layout, so this is a future compatibility gap, not an active publication
bypass. No actual SQL, source renewal or ledger mutation occurred. Preserve the
original freeze/red and require actual revision2 composition proof separately.

---

## ERROR-119 — SV attempt chronology could precede consumed authority

**Date:** 2026-10-15
**Severity:** medium
**Status:** fixed (native receipt source/mock scope)
**Found by:** Phase A lower receipt-facts negative
**Affected files:** `strategy/verifier_facts.py`

The old receipt check independently required consumption<=intent and attempt<=intent,
allowing an actual-shaped attempt reserved before the journal's consumed authority.
One original DID NOT RAISE/1.42s is retained. The extracted shared predicate now
requires consumed_at<=reserved_at<=intent.created_at, preserving original fence and
succeeded receipt chronology. Existing execution lease/identity checks stay in the
wrapper. Source/mock tests and Root3,234unit/69.80s/strict19 pass; no actual SQL
corruption or changed historical records were exercised. Keep the explicit original
attempt-chain negative; actual owner SQL qualification remains separate.

---

## ERROR-118 — Receipt caller loaded C bytes before invoking its READ adapter

**Date:** 2026-10-15
**Severity:** medium
**Status:** fixed (explicit receipt caller boundary; inherited adapter scope separate)
**Found by:** retained unchanged outer AcceptanceStore negative
**Affected files:** `strategy/verifier_receipt.py`, `verifier_facts.py`, `acceptance_store.py`

The original acceptance path called receipt verification before its protected-result
adapter; exact_artifact loaded the full C row first. The original outer-store test
observed one explicit full C get before nominated BrainDeniedError, failing/2.03s.
The shared lower facts gate now projects exact C metadata/target, invokes the
configured BoundedArtifactReader READ adapter, then loads and checks C bytes.
The execution wrapper requires that reader and retains lease/identity/fence/final
credential checks; only its two production callers forward their actual reader.

This establishes caller ordering, not literal zero body SQL before every contributor
READ inside the inherited adapter: its existing _snapshot/ancestor closure have a
separate internal ordering qualification limit. No returned-data leak or untrusted
SQL bypass was demonstrated. Preserve the actual boundary denial and scope it
accurately; any generic adapter change needs its own concrete probe/review.

Author154 focused/8.47s and Root3,234unit/69.80s/strict/lint/format19 pass. New real-owner
current-proof readers are source/mock-qualified only; no actual owner SQL, selection
approval, API wiring or revision2 activation is claimed.

---

## ERROR-117 — Lone CR escaped the support draft's literal quotation block

**Date:** 2026-10-15
**Severity:** medium
**Status:** fixed (supplied-data export and real CommonMark parser scope)
**Found by:** independent source review and retained actual parser negatives
**Affected files:** `company/cycle_artifacts/renderers.py`, `test_cycle_deliverable_exports.py`

### What happened and cause
The initial new renderer prefixed only LF-separated quotation lines. CommonMark
also recognizes CR and CRLF. An otherwise valid hashed source quotation containing
lone CR could produce image or raw-HTML parser nodes outside its intended literal
block. Six of24 real parser cases failed; no viewer execution or actual exploit
was performed. Source1 and all original vectors are retained.

### Fix and verification
Normalize CRLF/lone CR only in the human Markdown display before prefixing every
physical line. Original quotation UTF8, span SHA, dates and typed JSON stay exact;
human-export and dependent manifest/check hashes are regenerated. The24 actual
CommonMark parser cases pass, including mixed line ends/tabs/image/raw HTML.
Retained-vector replay proves all24 original data identities unchanged and18 CR
human views changed. Source2 has106 focused checks/strict17; Root3,182unit/59.00s
and strict/lint/format17 pass. markdown-it-py4.2.0 was already locked via Rich;
no production dependency or native authority changed.

### Prevention and scope
Keep parser-based line-ending cases and exact evidence-byte preservation checks.
This package compares supplied descriptions; real current engineering proof,
protected READ, publication and customer/operating acceptance remain separate.
Evidence: cycle-deliverables-pure-freeze-2.json f52cc1e2 and Root integration
receipt a69df4c7 under the dated private integration directory.

---

## ERROR-116 — First-plan PG fixture reused a stale pre-proposal CAS value

**Date:** 2026-10-15
**Severity:** low
**Status:** fixed (external qualification fixture; production CAS unchanged)
**Found by:** first actual Strategy publication PG run
**Affected files:** private `strategy_publication_pg_setup.py` and protocol tests

### What happened and cause
Actual v1 run96116 failed/4.30s after normal015/public source/governance setup.
Its initial propose created a proposed head, but the separate approval caller still
supplied expected_current_revision_id=None. Production correctly rejected the stale
expectation before any execution registration/action/hold/intent/attempt/proof.
The failed DB/source/tree and original source deadlines remain unchanged.

### Fix and verification
A new private v2 fixture expects the exact returned proposed revision for this
closed first-plan flow. It does not alter production require_cas, guess current
heads or generalize this rule to later revisions: a later proposal retains its
existing approved operative head. A strict pure protocol using real require_cas
retained the original failure, correct first flow and conflicting-head denial.
V2's19 pure checks/static16 passed, then actual22745 passed1/31.34s through B/S/C,
receipts/acceptance/replay and real final-flush expiry rollback. Root fresh SQL
verified final native records and no app backends; old v1 remains preserved.

### Prevention
Trace public head evolution and CAS separately for propose/approve/replay. Export
actual owner/policy/price/caps before claims, and retain stale-head negatives.
See the native Strategy PG checkpoint and v2 repair/source/actual receipts.

---

## ERROR-115 — Cache export cancellation lost owned filesystem operations

**Date:** 2026-10-15
**Severity:** medium
**Status:** fixed (finite local filesystem-operation scope)
**Found by:** Root unit regression and deterministic controlled-thread negatives
**Affected files:** `builder/cache_stream.py`, `test_native_builder_cache_stream.py`

### What happened and cause
The initial full unit run left the export's pending file after cancellation.
`to_thread(os.open)` could create a file before returning its descriptor to the
awaiting task; cancellation happened before the original try/finally. Subsequent
write/link operations could also outlive task cancellation and cleanup. A later
whole-suite pass did not resolve this race. Two finite event-gated original tests
failed/0.32s at open-after-create and link-after-commit boundaries.

### Fix and verification
One export now strongly retains its exact shielded pending filesystem task and
actual descriptor/stream/inode/link state. It waits for that operation to finish
through repeated cancellation before close and cleanup; cancellation rolls back
only its own committed final link and pending file. Foreign final/staging files
remain. Seven cache tests and 32 related checks pass, including live write and
conflicting-link cancellation. Root 3,101unit/40.27s, strict/lint/format2 pass.
Evidence: private `nexus-cache-stream-cancellation-20261015` and Root
`nexus-cache-cancellation-root-integration-20261015/ROOT_INTEGRATION_RECEIPT_1.json`.

### Limits and prevention
There is no hard filesystem/cancellation wall bound: asyncio cannot kill a blocked
filesystem thread. Identity-checked unlink assumes a task-owned private directory;
it does not claim atomic conditional removal against adversarial replacement.
Keep finite event gates, strong operation ownership and unconditional test cleanup.
No actual cache build, native runtime, database or production effect was exercised.

---

## ERROR-114 — Current strategy proof allowed blocked work and early body reads

**Date:** 2026-10-15
**Severity:** high
**Status:** fixed (pure/mocked current reader scope)
**Found by:** independent source review and retained concrete reader negatives
**Affected files:** `strategy/pair_reader.py`, `input_reader.py`, `original_reader.py`

### What happened
A selected succeeded S receipt could supply current proof when its logical author
work was blocked/unknown. Separately, full B/Brief ORM bodies were loaded before
per-resource current READ. Three original negatives failed/2.48s; the denied READ
case observed two early full body gets. No returned-body leak or SQL exploit ran.

### Root cause and correction
The new path omitted the existing current-target author state policy and used
full ORM rows to construct refs. It now rejects blocked/unknown author work,
projects five metadata fields, qualifies actual current artifact READ, then loads
exact full bytes. Retained negatives pass within65 candidate checks; independent
review and Root3,078unit/strict29 pass. Native SQL qualification remains required.

---

## ERROR-113 — Acceptance SQL timestamp diverged from immutable saved record

**Date:** 2026-10-15
**Severity:** medium
**Status:** fixed (mocked acceptance persistence scope)
**Found by:** independent store review and Root negative
**Affected files:** `strategy/acceptance_store.py`

### What happened
Changing only the saved SQL acceptance timestamp passed replay, even though later
management ordering uses that column. The original negative failed DID NOT RAISE.

### Root cause and correction
The existing generic decoder did not compare SQL recorded_at with its embedded
record date. New strategy persistence checks exact equality, full proof sets and
returned date<=final actual DB clock without replacing original replay dates.
Mocked tests and Root3,078unit/static29 pass; actual SQL proof remains pending.

---

## ERROR-112 — Strategy reader omitted restricted connection check

**Date:** 2026-10-15
**Severity:** high
**Status:** fixed (mocked configured-reader boundary)
**Found by:** independent source review and concrete reader negative
**Affected files:** `strategy/application_role.py`, native reader/store entry points

### What happened
A nominated privileged current-session result did not stop a protected original
read (one original DID NOT RAISE/1.14s). This is a trusted configuration rejection
gap, not an observed cross-company exploit.

### Root cause and correction
Generic runtime_transaction lacks the Brain transaction's role denial. Concrete
strategy entries now require the fixed same-session current_user role query to
return literalFalse before body qualification/writes. Missing/wrong-typed values
deny. Original source/test/logs remain; pure/mocked and full source regression
pass. The actual PostgreSQL packet must separately prove restricted behavior.

---

## ERROR-111 — Existing output rows weakened fresh publication effect state

**Date:** 2026-10-15
**Severity:** high
**Status:** fixed (mocked fresh actor publication scope)
**Found by:** Root and concrete actor reproduction
**Affected files:** `strategy/publication_state.py`, author/check actor gates

### What happened
With present B/S rows and an original failed/unknown effect, the initial concrete
author gate returned instead of denying (two original DID NOT RAISE/1.19s). No
actual receipt upgrade or native publication was executed.

### Root cause and correction
The reused generic known-output gate skipped effect state while the original
intent/hold helper was state-agnostic. Fresh strategy publishing now allows only
pending intent/no receipt or present rows with exact known succeeded receipt;
failed/unknown always deny. Corrected actor probes pass. Recovery remains separate,
same-fence semantics and unknown positive money remain unchanged.

---

## ERROR-110 — Check graph replay omitted exact derivation time and event identity

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** medium
**Status:** fixed (unhooked internal row-helper scope)
**Found by:** independent replay review and Root retained negatives
**Affected files:** `company/strategy/check_rows.py`

### What happened
The initial replay compared complete result/edge fields but accepted a changed
derivation timestamp or arbitrary event UUID. Both cannot be produced by the
writer, which shares one timestamp and derives event ID from company/dedup key.
Two retained mocked-row tests failed DID NOT RAISE. No native store was activated.

### Root cause
Exact graph equality omitted two persisted fields; a positive fixture also used
an arbitrary event UUID instead of the actual append_event recipe.

### Fix applied
Require derivation time==artifact time==event time and exact deterministic event
UUID/company/key. Correct only the synthetic fixture to the writer recipe.
32 slice tests and strict/Ruff/format5 pass; isolated2,953unit/33.43s and independent
review pass. These are mocked graph/source checks, not SQL rollback proof.

### Prevention
Exact replay must account for every immutable graph field. Retain actual writer
identity in positive fixtures rather than inventing compatible-looking rows.
See STRATEGY_CHECK_GRAPH_CHECKPOINT_2026-10-15.md for original red evidence.

---

## ERROR-109 — Verifier receipt gate omitted publication chronology

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** medium
**Status:** fixed (unhooked mocked-SQL receipt scope)
**Found by:** Root and independent receipt review
**Affected files:** `company/strategy/verifier_receipt.py`

### What happened
Initial exact journal/intent/receipt/output checks did not constrain the actual
artifact record's timestamp to original issuance and succeeded receipt time.
Two pure native-row negatives with metadata before issuance/after receipt failed
DID NOT RAISE. No caller endpoint or native acceptance store was active.

### Root cause
Final receipt<=now validated receipt time but did not prove that the referenced
publication metadata existed between original issuance and that receipt.

### Fix applied
Require original attempt<=intent<=publication metadata<=receipt<=final database
clock and authorization consumption<=intent. Keep original intent fence separate
from the current execute fence. The same two probes pass within56 focused checks;
coherent2,921unit/32.68s, strict/Ruff/format5 and independent review pass.

### Prevention
Validate each distinct persisted event's chronology against its original effect,
without inventing current timestamps or treating a present row as prior issuance
proof. Retained source/red logs are in STRATEGY_VERIFIER_RECEIPT_CHECKPOINT.

---

## ERROR-107 — Original bundle storage changed wire identity across encodings/processes

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** medium
**Status:** fixed (unpublished pure producer wirev2)
**Found by:** implementation reproduction and independent compatibility review
**Affected files:** `company/strategy/producer.py`, `producer_contracts.py`

### What happened
Canonical identity JSON changed original registration USD spelling0.08→0.080000:
the registration remained value-equal but its original wire digest changed.
Lossless Pydantic JSON avoided that scale change, but a separate cross-process
probe found its SourcePolicy.allowed_external_keys set changed array order.
Seed0 wrote one bundle; seeds1/2/3 restored equal inputs but regenerated different
bytes, and actual preparation rejected each original bundle hash. No strategy
artifact was published; the original sources/wire/ref/failures remain preserved.

### Root cause
Semantic identity canonicalization and lossless durable wire are different
contracts. Pydantic set serialization is not itself stable across hash seeds.

### Fix applied
Named `strategy-input-bundle-json-v2` retains validated JSON Decimal/date values,
sorts only reachable typed SourcePolicy.allowed_external_keys sets and object
keys, and preserves ordered arrays. No shared canonical recipe or old snapshot
is rewritten. A schema inventory confirms this is the only current reachable set.
Actual writer0 then fresh replay0/1/2/3 prepare/hash/digest equality now passes
within101 pure checks. Root2,865unit/32.17s, strict/Ruff/format17 and independent
review pass. This proves pure wire replay, not native protected publication.

### Prevention
Preserve original wire identity separately from canonical semantic digests;
exercise durable bytes across fresh interpreters/hash seeds. Freeze2/source and
retained probes are linked in STRATEGY_PRODUCER_CHECKPOINT_2026-10-15.md.

---

## ERROR-108 — Issued runtime relocates the host within the delegated scope

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** high
**Status:** open (source correction qualified; actual runtime proof pending)
**Found by:** actual methodv4 native qualification with retained parent facts
**Affected files:** `builder/contained_scope.py`, issued-process parent layout (correction pending)

### What happened
The actual original host self-membership changed from the exact delegated scope
to its `runtime` child after sandbox runtime issuance. All recorded Unit facts
and other Kernel identity/cap fields matched. The exact-root self-path invariant
rejected it, leaving sample0 and the native result unknown with no receipt.

### Root cause
The current layout assumed the host would remain directly in the scope root.
Exact actual-facts pure replay reproduces denial, with only that path different.
Runtime source research and a secure exact post-issuance layout correction are
being reviewed; no generic descendant membership exception is accepted.

### Fix applied
An ownership-bound post-seal path now preserves actual runtime-leaf facts and
unchanged root caps, while default pre-issue checks remain strict. Source414focus,
five recipe checks, Root2,981unit/strict23 and independent review pass. Actual
methodv5 qualification remains pending; retain the fourth failed case unchanged.
See ISSUED_RUNTIME_MEMBERSHIP_CHECKPOINT_2026-10-15.md.

### Prevention
Keep current live parent and workload layouts tied to actual runtime behavior.
Do not infer old-case causes, loosen caps or treat counterfactual DTO validation
as live qualification. See CONTAINED_PARENT_PATH_FAILURE_2026-10-15.md.

---

## ERROR-106 — Strategy source reader omitted citation-to-manifest links

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** high
**Status:** fixed (new unactivated source-helper scope)
**Found by:** independent source review and Root retained reproduction
**Affected files:** `company/strategy/source_inputs.py`

### What happened
The initial helper compared supplied citation records with actual source records
but performed READ/freshness checks over only the declared artifact/source
manifest. A different source could form that manifest while the cited source was
omitted. Two focused negatives failed with DID NOT RAISE, independently removing
the exact citation artifact or source contributor from the supplied manifest.
No endpoint or native strategy publisher was active.

### Root cause
The native manifest builder resolves artifact/source roots but copies evidence
IDs without expanding them. The source record join itself is not a READ gate;
later complete-reference checks cannot protect an omitted citation source.

### Fix applied
Before lookup, require each citation's exact artifact and source in the declared
manifest and require complete unique evidence IDs. Perform every declared
artifact's protected current READ and complete native manifest checks before
source-body comparison. The same two negatives now pass within17 focused tests.
Actual normal015 restricted PostgreSQL verifies valid READ, spliced-body denial
and final grant expiry after a real awaited grant read. It does not qualify a
native strategy, author registration, plan, acceptance or action.

### Prevention
Do not assume an evidence list automatically expands a native artifact/source
closure. Retained red log: `nexus-strategy-source-inputs-20261015/missing-source-link-red.log`.
Actual PG packetac5f213f and Root receipt1fa4fbab are preserved in the checkpoint.

---

## ERROR-105 — Strategy result descriptions and malformed-data handling were too broad

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** medium
**Status:** fixed (pure contract/checker scope)
**Found by:** supervised implementation and independent review agents
**Affected files:** `company/strategy/contracts.py`, `company/strategy/checker.py`

### What happened
Initial result decoding accepted a self-consistent checksum-valid PASS with only
one criterion or unsupported economic-merit criterion, although the checker
itself correctly returned inconclusive. Two constructor negatives reproduced it.
Separately, a generic ValueError catch could classify injected existing authority
denial exceptions as malformed strategy JSON; two pure boundary negatives proved
this behavior. No protected reader/publication/acceptance path exists yet.

### Root cause
Aggregate/checksum consistency did not require the complete closed six-criterion
PASS contract. Existing ExecutionDeniedError/BrainDeniedError inherit ValueError,
so the malformed-input catch also matched authority failures.

### Fix applied
Require exactly the six supported criteria for PASS while preserving supported
inconclusive results. Catch only dedicated malformed-data/JSON/Pydantic/Unicode/
recursion errors; actual permission/system failures propagate. Original red logs
and final51 focused green checks are bound by the StrategyBrief freeze2dfefa48.

### Prevention
Keep result-description invariants aligned with the pure checker, and nominate
actual exception subclasses before adding malformed-data catches. This proves
neither native acceptance nor live strategic quality.

---

## ERROR-104 — Contained inspect templates used JSON tag spelling as a Go field

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** medium
**Status:** source corrected/verified; fresh live containment qualification pending
**Found by:** actual diagnostic M1 qualification
**Affected files:** contained_discovery.py, contained_engine.py, contained_observer_io.py, contained_cleanup.py

The fresh diagnostic case completed both commands but recorded11 discovery
attempts, with retained first/last exit125 and the retained error “can't evaluate field Id”.
No object was sealed and no sample was collected; final diagnostic saysno_samples.
Native state correctly remains unknown with one attempt and positive unknown hold.

Podman's Go template field is ID while the ordinary JSON tag is Id. Its bare
`.Id` normalization does not rewrite the argument in `json .Id`. Root reproduced
the error with the exact retained stopped object and changed only `json .ID`:
the same read then exited0 and returned the expected identity/labels/stopped state.
No process was started, removed or upgraded by those reads. Official source:
https://raw.githubusercontent.com/containers/podman/v5.8.0/cmd/podman/inspect/inspect.go
InspectNormalize, lines261–263 at review.

Four duplicated fixed templates require the same narrow field correction. The
approved scope changes no liveness predicate, allowance, workload, limit or retry.
Both prior M1 actions/databases/results/containers remain preserved. This explains
the new diagnostic case; missing diagnostics still prevent a causal claim for
the original first M1. Fresh positive containment remains unqualified.

The exact four fields are corrected. Retained tests go from4 failed/6 passed to111
focused passes/1.35s, including actual stopped reply projection, zero-PID live
denial and immutable ID/company/action/image splice denial. Root coherent2,701unit/
25.89s/19 existing warnings and strict/Ruff/format6 pass. Independent review verifies
the four changes contain no other source edits. Complete-method v3 identifies the
Go-ID template correction; prior method/action pins cannot silently adopt it.

## ERROR-103 — Registry preservation test compared unordered raw JSON

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** low
**Status:** fixed; coherent integration regression passed2,565/24.80s
**Found by:** coherent integration suite, 1 failed / 2,564 passed
**Affected files:** tests/unit/test_company_model_observations.py

The preservation test confirmed equal model registrations, then failed because
the capability frozenset had a different raw JSON array iteration order after
reconstruction. The actual identity/signature contract uses canonical_json and
canonical_sha256. No capability, price or registration-content difference was
shown. Ten partial subprocess probes with seeds0–9 did not reproduce the full
suite's ordering difference; retain that negative result and the original failure.

Compare exact canonical bytes while retaining the full registration-equality and
binding assertions. This changes only the test, not registry serialization,
production authority, canonical goldens or eligibility behavior.

## ERROR-102 — Unknown containment result discarded the diagnostic basis

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** medium
**Status:** source correction verified; fresh actual diagnostic qualification pending
**Found by:** first actual configured contained M1 qualification
**Affected files:** builder/contained_invocation.py and process/observation diagnostics

Both actual command phases completed and supplied correct reports/inner limits,
but the native result remained unknown with host_containment_unproven. The
conversion retains neither raw infrastructure/sealed/sample diagnostic state nor
the final observer's failed qualification details. No containment sidecar or
successful receipt was produced, so this did not create false success. It prevents
the retained trace from establishing the exact reason for failed qualification.

Preserve the first failed controller/database/result and unknown cost hold. Do
not infer past live containment from a later stopped-container inspection. Source
control flow rules out a fatal discovery exception as the sole explanation for
this particular saved command envelope; other branches remain unresolved.

The next scoped change records bounded metadata-only raw/final diagnostics in a
private write-once store. It grants no receipt, cleanup or allowance authority.
Availability-classification changes, any fresh qualification and positive release
claims require separate review and evidence; the original action is not retried.

The diagnostic-only source now records bounded fixed-inspect first/last attempts,
complete counts/observed-byte hashes, raw infrastructure/sample summaries and final
observer status in separate private write-once records. Root compares actual raw
identity/runtime/output/sample chain/deadline before saving, then writes final
metadata before unknown or positive outcome branching. The new complete-method
version requires this concrete store; no diagnostic reference is a success ref.
Agent112 focused checks and Root53 integration checks pass; combined coherent
2,652unit/25.52s and independent source reviews are green. Actual first-run cause
remains unproven. If the original job end is exhausted, saving still denies:
there is no extra storage budget, guarantee for hard kills, or retroactive trace.

## ERROR-101 — OS fixture could lose a spawned worker before recording its identity

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** medium
**Status:** fixed in source2; all four actual OS recovery cases qualified
**Found by:** Root and independent source review before the first OS fixture launch
**Affected files:** tests/notification_process_controller.py and its unit tests

The first unlaunched controller read `/proc/PID/stat` after `Popen` but before
retaining the child handle. A failed read could leave a real child outside the
controller's cleanup inventory. Cleanup also stopped at the first metadata error,
which could prevent attempts to stop the other owned child.

Source2 retains the strong unreaped `Popen` handle immediately, with start identity
explicitly unavailable until observed. Cleanup attempts every owned child and
records each exit or error before failing as a whole. An observed identity mismatch
prevents a signal; an unavailable start never becomes an invented identity. Pipe
and log ownership also stays inside the startup cleanup boundary. Retained pure
probes cover the nominated post-spawn stat failure and two-child cleanup errors.
Source1 remains unlaunched and unchanged. All four intent/response/receipt/observation
cases then passed actual kill/immediate restart with both owned children reaped.

Root's coherent-source test run subsequently exposed two pure tests tied to the
private launch snapshot path (2 failed, 2,514 passed). Their mocked spawn scenarios
must nominate the test's current source location while retaining explicit wrong-
source denial tests. The corrected coherent suite passed2,518/24.36s. This test
portability correction changes no actual worker source, fixture record or runtime authority.

## ERROR-100 — SDK shutdown left the adopted host loop using a closed executor

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** medium
**Status:** corrected lifecycle qualified by actual rejected/uncertain SDK runs; original failure retained
**Found by:** first actual durable notification SDK qualification
**Affected files:** tests/notification_durable_pg_fixture.py lifecycle composition

The first accepted case reached actual SDK SUCCESS/submitted with one synthetic
POST and native succeeded receipt/tool1/model0/positive unknown billing hold. The
test then failed after DBOS.destroy at asyncio.to_thread writing shutdown evidence:
RuntimeError cannot schedule new futures after shutdown. Native replay and the
other two outcomes were not reached. No fresh operation was retried or reset.

Pinned DBOS3.2 _configure_asyncio_thread_pool installs its executor as the adopted
running loop's default. Destroy shuts that executor; subsequent host to_thread
calls still target it. This supports a fixture lifecycle cause, not a provider
or authority failure. A bounded isolated lifecycle or explicit host-owned executor
restoration passes four simulated adoption/shutdown regressions: capture the
active prior host executor, destroy SDK on that explicit executor, restore it
before later host I/O. Two separately reviewed actual SDK outcome runs then passed
with all captured threads stopped, exact supplied engine disposed and app backends
zero before native replay. The original accepted operation was not repeated. Preserve the original
SUCCESS/receipt/observation/hold and qualify any continuation as historical replay.

## ERROR-099 — Fresh acquisition added a clock after closing admission windows

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** medium
**Status:** fixed in NEW source and pure nominated-clock regression; actual PG pending
**Found by:** independent durable notification source review
**Affected files:** execution/notification_lease_recovery.py

The fresh helper qualified source/grant/approval/recipient deadlines, then its
caller awaited another db_now and checked only credential/configuration. The
outer preflight could cross the qualified window at that final await. This was
an acquisition contract gap; existing dispatcher rechecks mean no POST bypass
was demonstrated. Return the helper's already-qualified actual final clock and
perform only synchronous remaining checks afterward. The pure regression denies
expired returned clocks and asserts no additional clock await. Actual admission
and natural expiry qualification remain separate.

## ERROR-098 — Notification startup checked only the business database role

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** medium
**Status:** role/endpoint witness fixed in NEW source/pure ordering; actual SQL/SDK pending
**Found by:** independent durable notification source review
**Affected files:** execution/notification_worker.py

The worker checked business-factory NOSUPER/NOBYPASS but accepted a separate DBOS
system URL without observing that connection. This trusted configuration gap did
not establish an untrusted exploit. Supply one bounded explicit PostgreSQL engine
to DBOS and inspect its actual role/database name before launch. Name equality
alone does not prove cluster identity. Freeze2 requires exact configured endpoint
and observes the business PID/start/client record through the system engine while
that business connection stays open. Tests mock this witness; actual SQL visibility
remains pending. Existing singleton is denied; constructor
failure disposes the owned engine and keeps local services unset. Mocked role,
same-database and ordering tests pass; actual startup proof is still pending.

## ERROR-097 — User-manager parent validation required an absent delegation xattr

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** medium
**Status:** corrected user-manager source and actual mechanical finite-parent scope2 qualified
**Found by:** first actual finite-parent read-only probe
**Affected files:** builder/contained_kernel.py and parent contracts/provider evidence

The actual named20s user scope started and bootstrap observed active unit identity.
Provider denied at getxattr(user.delegate) with ENODATA; controller exited1 and
original launch PID/start was gone. No positive/foreign/expiry qualification.
The original bounded logs/packet/bootstrap/terminal receipts are preserved.

Pinned systemd261.2 cgroup.c cgroup_xattr_apply returns for non-system managers
before cgroup_delegate_xattr_apply; the documented marker is not set on this user
manager path. Correction must record explicit absent_user_manager rather than
pretend a marker exists: fixed --user bus, supported actual manager version, exact
UID/ownedunit/invocation/boot/path/controllers/limits and only ENODATA qualify the
absence. Other errno/malformed/value0 still deny. No marker writes or arbitrary
gate bypass. Provider/method identity must reflect the corrected evidence schema.
Primary: https://raw.githubusercontent.com/systemd/systemd/v261.2/src/core/cgroup.c .
Evidence: native-builder/root-parent-first-failure-scope.json. No corrected scope
has run; runtimev2 stays disabled.

## ERROR-096 — Targeted enqueue replay did not observe DBOS queue status

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** medium
**Status:** fixed in targeted source/pure gate; actual cancellation conservation pending
**Found by:** independent atomic enqueue source and pinned DBOS3.2 review
**Affected files:** notifications/worker_enqueue.py queue-result observation

Existing public scheduler queue readback pins exact name/queue/version/application/
serialization/inputs/ID but omits status. Pinned DBOS enqueue conflict updates only
time, preserving an existing terminal row. Thus targeted exact canonical replay
can report existing even for CANCELLED/ERROR/SUCCESS without an ENQUEUED operation.
This is scheduling/liveness metadata scope; no spend/authority bypass is proven.
The first actual PG positive explicitly observed ENQUEUED and passed1/9.41s.

Review a targeted notification status check in the same transaction after actual
queue readback and before final clocks. Terminal states must not become enqueued.
Possible active PENDING race needs explicit policy with actual pins; no generic
scheduler behavior or terminal resume is changed by assumption. Retain a probe
using public DBOSClient cancellation rather than seeded workflow status SQL.
No worker/provider launch or automatic cancelled workflow reset.

## ERROR-095 — Obsolete digest licensing used current-only historical references

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** medium
**Status:** fixed for observed r1/r2 obsolete metadata; current READ and history guards qualified
**Found by:** actual public source CAS/stale digest case
**Affected files:** notifications/qualified_obsolete.py and artifact/freshness qualification

Public source revision CAS accepted r2. The immutable owner report remained
original, current data differed, and no current/new digest was emitted. Consuming
the old wake correctly recognized obsolete state, then rejected saved r1 artifact
references through the current-only artifact path. Actual fourth case failed;
three separate loss cases passed14.16s. No obsolete acknowledgement/cursor proof.

The supplied-session artifact-reference method and freshness reference_sources
both demand current contributor revisions; body-free obsolete qualification needs
an explicit historical route. Current read/publication/acceptance remains current
only. Proposed correction preserves immutable bytes/complete lineage, current
READ/source policy/head availability/qualifiedTTL/recipient/final time and returns
metadata only. No general history flag, nested lock, old source refresh or new
report/permit/allowance is introduced. Original stale test remains unchanged.

Evidence: worker-digest-loss-stale-original-receipt.json, original corrected log,
OBSOLETE_DIGEST_HISTORICAL_REFERENCE_PLAN.md. The exact unchanged stale test now
passes1PG/5.47s; direct current/history/READ/tamper/finalexpiry7PG/32.77s pass.
Current-only methods remain unchanged. Root6NEWpure/0.86s/types6 and combined
2,040unit/21.60s pass. Mixed derivation/noTTL/quarantine and retention remain separate.
A separate first fixture failure
expected BrainDeniedError but actual required sender admission denied with exact
ExecutionDeniedError; its corrected test now proves ledger conservation.

## ERROR-094 — Delegated outer scope did not contain Podman payloads

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** high
**Status:** open for integrated runtime; local compatibility candidate qualified
**Found by:** Root inspection of actual CSV container PID/cgroup records
**Affected files:** builder runtime configuration/qualification; no production edit yet

Both real CSV payloads ran in sibling libpod scopes outside the proposed outer
job.scope. Actual self caps4GiB/2CPU/256PID and inner caps do not prove outer
whole-pair descendant cleanup. Original job records remain scoped accordingly.

Installed Podman5.8.6/official v5.8 docs informed an explicit cgroupfs + split
candidate. A tiny pinned-image no-network probe contained payload ancestry; a
changed4s outer probe captured six live runtime/conmon/payload identities and all
were absent after timeout. Engine cached Running with dead PIDs; ordinary rm/sync
failed and only exact labelled synthetic object was force-removed. No production
cleanup claim follows. Integrated versioned ABI, manager-compatible cleanup and
actual full descendant gate remain required. Evidence: root-native-outer-containment-
gap.json and cgroup-split-qualification-20261015/manifest.json.

## ERROR-093 — Known CSV replay fixture assumed the wrong lease mode

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** medium
**Status:** fixed in cleanup scope; preserved known replay qualified, original full test remains failed
**Found by:** actual public native CSV pair test
**Affected files:** tests/csv_native fixture and builder/engineering_cleanup.py

The actual author/verifier jobs and protected acceptance succeeded, then the full
test failed1/61.73s asserting generic claim.mode == reconcile for a known succeeded
receipt. Generic claim defaults execute; reconcile_only requires unresolved effects.
The native runner routes existing issuance to reconcile before prepare/begin/invoke,
but its engineering cleanup hook currently rejects the valid current execute lease.

Do not change generic claim or repeat the two consumed jobs. Preserve the failed
assertion/rows/unknown holds; qualify a narrow cleanup path accepting current execute
only under normal active/unpaused admission, while reconcile retains historical
checks. Exact succeeded receipt/protected summary/current fence/immutable stopped
ID remain mandatory. A preserved-state replay-only continuation must prove zero
new invocation/attempt/hold; production mode is not itself effect authority.
Evidence: csv-node-v4/native-fixture-job-1.log and root-native-first-failure-scope.json.

Later preserved-state proof: first recovery-only driver returned both actual saved
results with zero prepare/invoke, then failed a fixture receipt construction after
the correct witness-cache cleanup. Actual finally released both leases/pauseFalse.
The remaining-only driver uses actual stored receipt, proves pausedexecute denial,
exact proof/acceptance replay and currentREAD revoke denial; terminalfences7/6
released, immutable native history/captures unchanged. Root12focused/0.96s, strict
/Ruff2 and coherent1,952units/21.71s pass. No jobs/allowances were repeated.


## ERROR-092 — Notification tick omitted the configured fact-resource comparison

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** medium
**Status:** fixed in worker emission binding
**Found by:** independent frozen tick source review
**Affected files:** notifications/worker_tick.py; retained expected-resource unit probe

### What happened
A typed, legitimately readable decision/failed receipt resolving to a second
catalog resource reached the emitter despite the WorkerSubject expected-resource
pin. The unchanged pure probe failed2/1.55s at an emitter sentinel. This shows a
configuration binding omission; native READ remained required and no disclosure
or protected admission bypass was demonstrated.

### Root cause and fix
Registration checked the non-digest expected resource against facts.resource,
while actual action selectors dynamically derive their resource from the immutable
journal and catalog. Compare the actual qualified projection.resource to the
configured subject before emission; keep the inherited source/final-clock checks.
The same retained cases pass2/1.23s. Root coherent1,950units, strict/Ruff14 and the
actual first positive/sequential replay1PG/8.08s pass. Broader worker boundaries
remain separate gates.

### Prevention
Keep the two typed dynamic-selector mismatch cases and the exact single-resource
configuration limitation. Evidence: notifications/worker-tick-static-review-freeze-2.json
and worker-expected-resource-retained-red.log/fixed.log.

## ERROR-091 — New worker guard parser and company boundaries were incomplete

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** medium
**Status:** fixed in pure configuration and optional operation seams
**Found by:** Root source review and retained notification probes
**Affected files:** notifications/worker_config.py, native_fact_emitter.py,
qualified_consumer.py, managed_preparation.py

The new reader allowed nonstandard JSON to reach declaration parsing and exposed
a RecursionError for bounded deep JSON. Same genuine owner/workspace identity also
passed the guard's entry check when scope/selector/control/catalog company differed;
native permission remained separate, with no demonstrated live publication bypass.
The retained clean red run failed10/passed39 in59.06s.

Reject nonstandard constants and deep recursion with the safe configuration error.
Require exact guard company metadata on each optional guarded entry before native
reads, retaining all native authority checks and default None behavior. Agent128
focused/2.12s and Root51guard/seam/1.27s pass; strict/Ruff/format9 and Root coherent
1,922units/21.06s pass. Actual tick and PG final-clock tests remain open.
Evidence: notifications/worker-config-guard-seams-freeze-2.json and original/red logs.

## ERROR-090 — CSV description helper silently selected a verifier role

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** low
**Status:** fixed in exact pair validation
**Found by:** independent Nodev4 source review
**Affected files:** builder/csv_source_checks.py

The pure description helper selected the author receipt for result==author and
the verifier receipt for every other result. A modified result outside both exact
descriptions, with recorded_at changed1s, passed. Retained pure probe failed1/0.67s.
No protected publication bypass was demonstrated: actual saved-result/protected
summary digest and native admission still reject spliced operative inputs.

Require exact (result,witness) membership in the actual author or verifier pair,
then derive an explicit role before selecting its receipt/output. Extraneous and
crossed pairs deny. Unchanged probe, two crossed cases and descriptions pass62
focused checks/1.41s; Root's61loader/observation units/1.13s and strict/lint2 pass.
Evidence: native-builder/csv-exact-pair-amendment-1.json and retained original probe.

## ERROR-089 — Known engineering recovery left stopped owned containers

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** medium
**Status:** fixed in the engineering-specific reconciliation cleanup slice
**Found by:** post-process recovery inspection
**Affected files:** builder/engineering_cleanup.py, builder/engineering_runner.py

Actual result/receipt kill points occurred before generic normal-run removal.
Reconciliation rebuilt acceptance and released native capacity, but two exact
owned containers remained stopped with exit0. The original four recovery facts
are valid; stopped-container cleanup was incomplete and its inspection is retained.

A separate service requires current membership/reconcile fence, actual succeeded
receipt and complete protected result summary hash/spec/proposal/intent fence.
It captures and reinspects exact stopped action/company/image labels, checks the
final DB lease clock, then removes by immutable full ID without force/prune.
Missing inventory is idempotent; engine errors, mismatches, live/unknown containers
and stale leases deny. Infrastructure cleanup can proceed for expired source
without returning private results or recording new proof/acceptance/spend.

Ten units/0.99s, actual final-fence denial1PG/10.64s and known-hook missing-container
replay1PG/8.52s pass. Actual removal of only the two retained IDs completes1.64s;
native before/after history hashes are identical, positive unknown holds remain,
leases release at fence5. The OS wave predates this hook and was not rerun; do not
merge those scopes into a repeated process claim. Evidence: engineering-cleanup-
freeze-1.json and engineering-retained-container-cleanup-outcome.json.

## ERROR-088 — Notification authorization returned after recipient registry loss

**Date:** 2026-10-15 (Asia/Bangkok)
**Severity:** high
**Status:** fixed; retained actual probe closed
**Found by:** independent notification authorization review
**Affected files:** notifications/worker_authorization.py

After the second actual draft admission, authorization awaited action authority
and the final DB clock without rereading the external recipient pin. Removing
only the disposable recipient file at that boundary returned authorized and
committed a new hold0→1. Original actual probe failed1/5.58s, hook count1.
This establishes erroneous consumption, not a send: no provider was invoked.

The final synchronous recipients.require_current check now follows the last await,
alongside native, credential and exact approval windows. The unchanged probe is
included in the final ten-case normal015 gate10passed/42.96s. Independent source
review confirms the placement; its report distinguishes Root execution from
the reviewer's read-only verification. Original logs are retained under
notifications/worker-authorization-recipient-original-pg.log in the dated evidence.

## ERROR-087 — Client setup awaited past current notification source authority

**Date:** 2026-10-14; final package checked 2026-10-15 (Asia/Bangkok)
**Severity:** high
**Status:** fixed in the new credential wrapper
**Found by:** notification wrapper boundary review
**Affected files:** notifications/worker_dispatch.py

Actual fixture source READ was revoked inside awaited client setup after the
original full precall check. One mock POST occurred before a later append denied;
original probe failed1/7.33s. This is bounded synthetic setup behavior, not live mail.
Move full inherited native precall and complete local-time checks inside the open
client context, after setup; retain credential verification inside the request
method. The unchanged source probe passes1/6.13s with zero POST and public release
conserving one attempt, permanent slot and positive unknown hold. Final frozen
7PG+7unit14/47.42s passes; shared dispatcher/effect/transport source is unchanged.
Evidence: notifications/worker-credential-wrapper-freeze-1.json and setup-source logs.

## ERROR-086 — Engineering worker observation outlived the source window

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed in the new local worker observation
**Found by:** Root boundary review and recovery agent actual reproduction
**Affected files:** execution/engineering_worker_observation.py

Actual public ingestion with20s TTL, two native builder receipts and protected
acceptance reproduced an accepted observation after its source expired during the
last CostHold lookup. Original probe failed1/24.01s (DID NOT RAISE), with the nominated
delay observed once. Earlier freshness validation did not protect subsequent awaits.

Retain actual QualifiedFreshness through the last DB clock alongside proof/source
grants, lease and sealed credential. Shared freshness behavior is unchanged.
The unchanged probe plus known-output replay pass2/33.75s on the final stable source.
A preceding head-deadline correction pass1/24.59s is retained as an earlier source
version, not evidence for the final amendment. The typed test-only TTL parameter
preserves default300s and uses real policy/ingestion, without SQL freshness edits.
Evidence: native-builder/engineering-worker-credential-freeze-1.json and the
original/fixed final-source logs under the dated implementation evidence directory.

## ERROR-085 — Engineering context failure leaked an acquired lease

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed in the new local worker context
**Found by:** Root boundary review and recovery agent actual reproduction
**Affected files:** execution/engineering_worker_context.py

Source resolution failed after actual same-dispatch lease recovery, before the
outer worker received a context. Its finally block therefore had no lease to
release. Original actual probe failed1/8.53s with a live worker/expiry still stored.
Context acquisition now releases its exact current lease on preparation failure,
propagating a failed release rather than manufacturing successful cleanup.
The unchanged failure case and known-output worker replay pass2PG/18.94s, with
M1 facts, attempts and positive unknown billing conserved. The credential amendment
also passes the current known/cleanup/default three-case gate3PG/29.34s.
Actual DBOS/process-kill recovery remains a separate unrun gate.

## ERROR-084 — Native decision publication required irrelevant model evidence

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed in the local native decision admission slice
**Found by:** notification worker credential integration
**Affected files:** company/brain/native_fact_admission.py

Actual empty-model owner notification admission succeeded, but a real pending
decision source failed publication because decision_deadlines unconditionally
looked for model health/evaluation windows for every child. Original restricted
PG case failed1/4.70s through the actual NativeFactEmitter/Reader with
"Native decision profile evidence is unavailable".

Validate each complete configured child profile before collecting deadlines.
Only an exact configured native engineering or notification identity skips the
model-only window; a literal name, missing configuration or corrupt unselected
tuple still denies. Ordinary model evidence retains its actual finite window and
fresh observation behavior. Grants, source, membership, current owner and all
other native publication checks remain unchanged.

Nine new pure cases and focused89cases/1.17s pass, strict/Ruff/format2files pass.
The unchanged actual source fixture now passes1/6.76s, including native draft and
one mock submission with replay/no second POST. The distinct pending source action
remains unapproved. This is offline integration, not live email or worker release.
Receipts: notifications/native-decision-profiles-* and
worker-credentials-source-original.log/worker-credentials-first-positive.log
under the dated implementation evidence directory.

## ERROR-083 — JSON serialization normalized copied quota values before validation

**Date:** 2026-10-14
**Severity:** medium
**Status:** fixed, unchanged raw-quota probes closed
**Found by:** independent notification profile review
**Affected files:** notifications/native_profile_checks.py, management/native_execution_profiles.py

In pinned Pydantic2.13.4, a corrupted model_copy quota with model_requests=False
serialized as integer0. JSON reconstruction alone admitted malformed metadata;
float/string copies could produce serializer warnings instead of deliberate denial.
Notification original36cases passed33/failed3, and Root's engineering child/root
bool probes failed2/1.42s. Both native paths now validate actual raw AttemptQuota
fields before any JSON dump. Notification43cases/1.44s and unchanged engineering
probes pass; independent original-catalog coexistence3cases pass1.60s. Root's
complete integration1614units/15.60s and strict/lint13files pass.

This is exact typed-metadata validation, not demonstrated extra runtime allowance:
actual immutable registered counters and quotas are separate and unchanged. Keep
raw literal checks ahead of serializers; do not relax limits or default profiles.

---

## ERROR-082 — Backup owner authorization used an independently supplied database

**Date:** 2026-10-14
**Severity:** medium
**Status:** fixed, actual unchanged configuration-context probe closed
**Found by:** independent operator backup review
**Affected files:** operations/backup_authority.py, backup_capture.py, backup_binding.py

A source-configured coordinator accepted owner pause/quiescence from a TARGET
factory. This is a trusted configuration defect; no untrusted caller exploitation
or source-state violation was induced. The unchanged public regression failed
1/124.54s. The owner transaction now matches actual DB/port/Unix transport to the
adapter's actual SOURCE and its observation of the owner's live backend PID/start.
App settings access was denied; no role privilege was added. Pinned asyncpg0.31.0
transport access is isolated and unsupported interfaces fail closed. Two actual
read-only PG and seven driver negatives pass9/7.42s. The amended full matching
drill then passes1/26.67s on fresh pair2, preserving both original databases.

Preserve actual endpoint/context binding at every owner gate. URL strings and
decoded metadata alone are insufficient. This is local matching recovery, not
lost-source recovery, cryptographic remote attestation or production RTO.

---

## ERROR-081 — An exited process leader left its owned descendant alive

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed, unchanged owned-process cleanup probe closed
**Found by:** operator process cleanup verification
**Affected files:** operations/backup_process.py

Group TERM was followed by group KILL only while the leader remained alive.
A TERM-ignoring child survived an already-exited leader (original1failed/1.61s).
Cleanup now makes the final bounded kill/reap decision for the exact owned group
independently of leader state. Five process cases pass1.99s; an independent
cancellation case passes1/2.51s, including the TERM-ignoring descendant.

Keep process ownership and group identity explicit; never apply this cleanup to
unrelated or shared services. An exited leader is not proof of drained descendants.

---

## ERROR-080 — Engineering replay depended on a process-local witness cache

**Date:** 2026-10-14
**Severity:** medium
**Status:** fixed, unchanged fresh-publisher replay closed
**Found by:** engineering acceptance integration
**Affected files:** builder/engineering_runner.py, engineering_artifacts.py

A fresh publisher could not reconcile a known native result because its witness
cache was empty (original1PGfailed/16.06s). The engineering wrapper now checks
actual native action/intent/proposal/fence, loads the pinned durable witness, then
delegates to the unchanged generic runner; terminal entries are cleared. The
unchanged test passes1PG/14.47s with no reissue, counter, receipt or billing change.
This is fresh-object recovery, not an OS-process restart proof.

---

## ERROR-079 — Engineering acceptance omitted a proof's final READ deadline

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed, unchanged actual proof-expiry probe closed
**Found by:** engineering protected publication review
**Affected files:** builder/engineering_acceptance.py

The proof's unique READ grant expired during the last awaited work lookup, but
acceptance still committed. The final gate now retains complete proof/source/output
grants and freshness, awaits the work lookup, then samples the clock and checks
lease and all retained dates. Publication and replay share this gate. Original
two-boundary run failed2/63.07s; corrected6PG/122.89s and final coherent27unit+
9PG/164.87s pass. Immutable acceptance and unknown costs remain on denied replay.
An independent additional expiry invocation later failed during stale-source setup;
it does not independently prove this boundary and remains recorded separately.

---

## ERROR-078 — Engineering declaration did not bind the registered procedure

**Date:** 2026-10-14
**Severity:** medium
**Status:** fixed, unchanged actual procedure mismatch probe closed
**Found by:** engineering native declaration review
**Affected files:** builder/engineering_metadata.py, engineering_inputs.py

A declaration naming an unrelated procedure still prepared protected proof.
Metadata now resolves both actual current child bindings, requires the same plan
and procedure, and compares the declaration before protected result reads and at
commit. Original/corrected/final evidence is retained with ERROR-079. No work
registration, allowance, receipt or schema was rewritten.

---

## ERROR-077 — Native catalog pins conflicted with a selected model view

**Date:** 2026-10-14
**Severity:** medium
**Status:** fixed, unchanged independent coexistence probe closed
**Found by:** combined native admission and model gateway review
**Affected files:** company/management/plan_support.py

### What happened and fix
A valid catalog with two models and unselected native profiles passed construction
and current profile admission, but model action admission narrowed its models to
one while retaining native tuples pinned to the full registry SHA. The native
validator rejected the derived view. The unchanged independent pure probe failed
1/1.77s; default-empty native configuration passed the same action.

The full original native tuple remains checked before selecting any model action.
Only the derived selected-model view clears native_profiles alongside its existing
model/observation narrowing. No original registry, tuple, work registration or
model allowance changes. The unchanged independent probe and a malformed
unselected native tuple denial pass2/7.19s. Final combined1516unit35.14s and
amended strict/Ruff/format pass; original failure/input/source records are retained
in model-gate/native-observation-cross-review.

### Prevention
Test catalog coexistence through actual constructors and public action predicates.
Preserve complete validation before narrowing a derived view; do not weaken the
native helper or skip malformed unselected configuration globally. Native model
tools remain denied. No live provider, engineering acceptance or activation claim.

---

## ERROR-076 — Restore directory replacement redirected output writes

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed, independent unchanged local probe closed
**Found by:** scoped operator backup path review
**Affected files:** operations/backup_files.py

### What happened and fix
After creating the new empty target, restore closed its parent descriptor and
used pathname writes. Replacing that target with a symlink to another synthetic
private directory redirected dump/artifact writes before the final nofollow open
failed. Original unchanged unit probe failed0.35s. Root now opens the target from
the still-anchored parent before any write, uses directory-relative nofollow
traversal/file creation throughout and checks final inode/visible namespace.
The unchanged reviewer probe passes0.26s; Root repeat passes0.17s. Only owned/tmp
fixture paths were used; no real backup, credential or user-data write occurred.

### Prevention
Leaf O_NOFOLLOW cannot protect mutable ancestor paths. Retain the created target
descriptor and relative directory walk through all writes. Preserve the original
probe/hash and source snapshots in backup-review; no permissions or assertions
were relaxed. This does not prove database capture consistency or operating restore.

---

## ERROR-075 — Inbox pagination anchor was outside current licensing

**Date:** 2026-10-14
**Severity:** medium
**Status:** fixed, independent original probe closed
**Found by:** combined owner inbox API review
**Affected files:** notifications/inbox_store.py

### What happened and fix
after_id resolved an owner row for ordering but the final source/recipient barrier
covered only candidates/lookahead. Actual source READ revoke followed by an empty
page after the oldest anchor returnedHTTP200. No body disclosure is claimed.
Original unchanged restricted015 probe failed18.05s, then passed17.83s after the
anchor joined licensing and at most9 total queried identities. Cursor+limit8 uses
at most8 candidates plus anchor; a conservative continuation may lead to an empty
licensed page and does not claim has_more. Source/recipient final-await expiry and
current/obsolete pagination remain guarded. Prior and amended snapshots preserved.

### Prevention
Count and qualify every metadata query row, including ordering anchors and skipped
or lookahead records. Preserve original adversarial HTTP probe and final clock/
recipient pins; existence alone is not a current read license. See external
notification-inbox-review/verdict-fixed.json and inbox-anchor-amendment-v1.json.

---

## ERROR-074 — Direct model observation helper ignored a later conflicting record

**Date:** 2026-10-14
**Severity:** medium
**Status:** fixed, independently reproduced and rechecked
**Found by:** independent combined eligibility review
**Affected files:** management/model_observations.py

### What happened and fix
The complete PlanAdmissionCatalog constructor rejected duplicate observations,
but its standalone resolver selected and validated only the first matching row.
Two individually valid same-model observations, healthy then unhealthy, returned
the first positive through unchecked direct/helper configuration. This is a
helper fail-closed gap, not demonstrated HTTP observation authority. The exact
original probe fails then passes unchanged after complete-tuple validation before
selection. Explicit32 bound and unknown/duplicate/company/revision/hash checks
now apply to every direct resolver invocation. Selected model request admission
narrows both registrations and observations together, retaining multi-model use.

### Prevention
Keep exact original adversarial probe and valid conflicting-record regression;
constructor validation does not replace direct public helper checks. Evidence:
model-gate/observations-review-duplicate-valid-records{,-fixed}.log.

---

## ERROR-073 — Management canonical hashing omitted date-only price metadata

**Date:** 2026-10-14
**Severity:** medium
**Status:** fixed, scoped canonical encoding
**Found by:** explicit immutable model registration observation tests
**Affected files:** management/canonical.py

### What happened and fix
Hashing a complete model registration reached PriceCard.as_of, a Python date.
The management encoder handled aware datetime but left date unchanged; JSON
raised TypeError instead of producing a registration pin. Root's first11-case
implementation run failed and remains in observations-implemented.log. Add ISO
date encoding after the datetime branch, preserving timezone normalization for
instants. Focused tests now retain the exact date and a pre-observation no-price
catalog golden SHA340636ac…cca8. No previously encodable value or hash changes.

### Prevention
Complete typed boundary hashing includes nested dated pricing, not only hand-made
string references. Preserve old catalog golden and actual observation expiry
denial; source receipt dates remain separate from observation dates.

---

## ERROR-072 — Notification precall used a captured target grant after revocation

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed, independently validated scoped dispatch correction
**Found by:** Root independent actual PostgreSQL dispatch boundary probe
**Affected files:** notification dispatch precall

### Reproduced behavior and required correction
After a real committed M1 intent, the actual owner revoked READ on the distinct
notification target through the public access store. The frozen dispatch precall
rechecked source/action but retained only earlier target deadlines. The original
normal014 probe did not deny dispatch, failing its expected rejection assertion.
The correction re-reads current target access and actual configured managed execution
before HTTP, retaining fresh deadlines and checking the final lease clock after awaits.
Original unchanged probe passes1PG17.99s; Root corrected coherent13PG passes237.40s.
The prior freeze is retained; only dispatch_store and an owned regression amend it.
All HTTP is explicitly mocked, no real email was sent. Evidence:
notification-review/test_target_before_post.py, target-first.log, target-fixed.log and verdict.json.

---

## ERROR-071 — Receipt event hook needed a final current lease clock

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed, scoped new receipt hook
**Found by:** actual two-second lease and awaited receipt-event probe
**Affected files:** shared effect receipt transaction with configured publisher

### Reproduced behavior and fix
Without the final check, an awaited event hook crossed the actual lease deadline
and committed the outcome/cost/event. The corrected boundary checks the current
native lease/fence after the hook and final flush, rolling all three writes back.
The actual-expiry original probe passes unchanged in the final12PG matrix and
independent4PG review. An earlier fixture tried renew(ttl=1), which correctly does
not shorten an existing60s lease; that failed to test expiry and was corrected to
an actual short initial lease. Default unconfigured receipt behavior is preserved.

---

## ERROR-070 — Receipt publisher accepted a transient invented outcome row

**Date:** 2026-10-14
**Severity:** medium
**Status:** fixed, scoped new receipt publisher
**Found by:** direct public publisher probe against actual intent state
**Affected files:** native failed receipt event publisher

### Reproduced behavior and fix
A transient copy of the real intent, changed to failed in memory, originally
created a wake while the database intent still had no receipt. The publisher now
re-reads persisted native work/intent and requires the actual session-owned rows,
exact immutable receipt/action/run/trace/resource binding. The unchanged direct
probe and actual failed-process positive pass, including independent review.
This closes false event publication; it does not claim an external send happened.

---

## ERROR-069 — USTAR cannot export pnpm CAS long filenames

**Date:** 2026-10-14
**Severity:** medium
**Status:** fixed in bounded public-cache helper, not a project-build acceptance
**Found by:** Root prelaunch review and harmless actual tar reproduction
**Affected files:** builder cache import plan/archive extraction

### Cause and fix
Pinned pnpm9.12 uses126-byte SHA512 basename tails, sometimes with-index.json.
The planned USTAR export cannot encode those names. Harmless reproduction exited2
with the expected long-name error; GNU format exported the same bytes with exit0.
The helper now exports normalized GNU entries; extraction rejects unsupported
PAX/ownership/time/link/sparse metadata while preserving bounded ordinary long
names and readonly executable files.20helper tests pass; actual complete cache
import later passed26.22s. Frozen amended package and receipts remain separate
from project resolution, ARM64 and native engineering acceptance.

### Prevention
Qualify actual package-store filenames and safe decoder behavior before large
cache import. Scope source/reproducer/receipts are in native-builder evidence;
the Nexus skill records the verified format procedure and remaining limits.

---

## ERROR-068 — Report preparation link used the wrong generated action field

**Date:** 2026-10-14
**Severity:** low
**Status:** fixed
**Found by:** TypeScript build during owner report UI implementation
**Affected files:** frontend report preparation panel

### Cause and fix
The journal ActionRecord nests its ID under proposal. The first link assumed
action.action_id; the actual generated API type rejected it. The link now reads
action.proposal.action_id, and the corrected build passes15.96s. Keep generated
schema types authoritative for action links rather than guessing DTO fields.

---

## ERROR-067 — Native builder recovery accepted a guard for a different identity

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed
**Found by:** independent actual restricted PostgreSQL builder review
**Affected files:** native builder runner public reconcile/result disclosure

### Reproduced behavior
After one actual native run and revoking the actor's source READ, run with the
same actor/guard returns no result. Public reconcile with that actor's exact
lease/action/spec but an owner-identity guard returned private saved logs and
artifacts. The original unchanged probe fails1PG5.14s in builder-review/
test_reconcile_guard.py and reconcile-first.log. Frozen39source hashes matched.
This is actual disclosure-boundary evidence, not a theoretical review comment.

### Fix and independent validation
Run and public reconcile now share exact guard/spec/policy/actual lease/identity/
output target qualification before saved data reads. Recovery also checks the
actual current work/action. Guard identity cannot replace the authenticated caller.
The unchanged original probe passes1PG4.84s. Amendment SHAaf7641c3dbe77b14595fa7a193fcf484d92bf5822e05425d2d9d213e6770ec9d
and runner SHA72c3718a53b1c629a09faa3f32493896eee3f132ab1ce7957784149e45bcf19a
match the independently checked files;38 original source files remain unchanged.
Scoped verdict is builder-review/verdict.json, SHAbc63ac56fcde638875de01531706ba5ef1b66b1037d0b4e89eaf6c5ab0456fa7.
The combined regression is separate. Historical evidence remains scoped; full
M4 qualification, engineering acceptance and production activation are unclaimed.

### Prevention
Retain the original actual source-revocation/guard-splice probe at public recovery,
alongside normal run permission checks. A guard is bound input, never authority
to replace the caller at a recovery or disclosure boundary.

---

## ERROR-066 — Metric foreign keys lacked complete covering indexes

**Date:** 2026-10-14
**Severity:** medium
**Status:** fixed
**Found by:** stable whole unit regression after scoped migration/metric checks
**Affected files:** `management/metric_models.py`, uncommitted `company_013_metric_observations.py`

### What happened and fix
The exact selected goal/plan FK was valid, but its initial query index covered
only the first three of five FK columns. Goal-revision and recorded-owner FKs also
needed dedicated covering prefixes. The unchanged existing all-management-FK
test found this in the first whole snapshot:1121pass/1fail. Scoped earlier index
inspection had checked query access paths and was incomplete for this rule.

Root expanded the plan index to the complete five-column FK and added goal-ref
and owner indexes in the still-uncommitted migration. No old released migration
was changed. The original all-FK test remains unchanged; focused3unit0.61s and
whole1122unit20.46s pass. Fresh/repeat/metadata/downgrade plus seven restricted
schema cases pass8PG25.89s. The schema-only placeholder is not business proof.

### Prevention
Run existing repository-wide metadata invariants at the stable integration gate,
alongside actual fresh-install comparison; a query index alone may not satisfy
the full FK prefix. Retain the scoped review limitation and original failure.

---

## ERROR-065 — Metric missing-record response was flattened into validation failure

**Date:** 2026-10-14
**Severity:** low
**Status:** fixed
**Found by:** actual restricted PostgreSQL metric HTTP matrix
**Affected files:** `api/company_metric_routes.py`

### What happened
The new controller returned422 for a missing observation instead of404. The
positive observation/replay/current checks and eleven denial cases passed before
the original missing-record assertion failed. No deployment or data leak occurred.

### Root cause and fix
Pinned Litestar2.24 NotFoundException also inheritsValueError, so the controller's
generic validation handler caught it. A specific NotFoundException handler now
preserves404 with a generic unavailable detail. The unchanged failing real HTTP
case passes in19.29s; original matrix1fail/11pass61.55s remains in metric-api-first.log.

### Related fixture correction
The first new source-revocation HTTP test used nonexistent readable/writable
fields rather than the actual ResourceAccessChange.active flag. It failed at
fixture construction, while the owner-after-lookup revocation case passed. Read
the exact typed declaration before building an integration fixture; keep setup
failure separate from permission rejection evidence.

---

## ERROR-064 — Runtime schema import interrupted UAT restart

**Date:** 2026-10-14
**Severity:** medium
**Status:** fixed
**Found by:** actual UAT startup and schema test collection
**Affected files:** `api/company_openapi.py`, `company_app.py`

### What happened
The new response-schema adapter imported GoalRevisionRecord from the wrong module.
A suggested correction also named a nonexistent module. The local UAT API restart
failed twice. Root reported import success before awaiting the process's actual result.

### Root cause
Module location was inferred rather than searched, and a running tool handle was
mistaken for successful completion.

### Fix applied
Actual rg located GoalRevisionRecord in goal_store.py:42. The import was corrected;
separate import process exit0, actual API health200/runtime schema export and the
JSON response shape unit1pass4.34s confirm correction. Original startup/collection
failures remain in owner-uat and company-schema evidence logs.

### Prevention
Search exact definitions first; await the exact tool handle's terminal result before
claiming a successful import/startup. Keep source presence and process status separate.

---

## ERROR-063 — Native final intent omitted the action authority expiry

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed and independently rechecked
**Found by:** independent actual EffectIntent.flush expiry probe
**Affected files:** `execution/native_report_intent.py`

### What happened
Actual owner approval remained valid through preparation/current authority checks,
then expired during a real delayed intent flush. The final pure native clock checked
source/grant/lease/profile windows but omitted the exact/standing authority deadline;
intent consumption returned normally after expiry (original1PG42.82s failure).

### Root cause
The compiled native timing snapshot did not capture the immutable approval/grant expiry.

### Fix applied
Capture public action_expiry(session, JournalAction) during native intent validation
and include it in the final pure deadline checks after all awaited writes. No approval
fields, counts or source rules are relaxed. The unchanged authority repro plus pending-blob
cost confirmation passes2PG45.07s. Full combined review/process proof remains separate.

### Prevention
Retain the original exact/standing authority-window probe, alongside final source,
recipient, profile and lease timing cases. A successful publication gate later cannot
justify an unauthorized already-consumed intent/counter.

---


## ERROR-062 — Conditional file mutator overwrote the wrong module

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed
**Found by:** report test collection during integration
**Affected files:** `company/management/acceptance_provenance.py`

### What happened
A local Python edit reused a previous file's text variable when evaluating a conditional.
It wrote retrieval-record code into the acceptance provenance module, removing three
public exports. Report test collection failed; no business execution or release occurred.

### Root cause
The mutation changed the path before refreshing its text and used a conditional expression
against the stale variable. The editor assumed the intended replacement had succeeded.

### Fix applied
Restored the exact committed module, reapplied only the intended artifact ancestry import
and `reference_sources` delta, checked public imports and reran actual reference/report
paths. The original collection failure remains in `management-reports/final-pg.log`.

### Prevention
Use explicit file patches or independently parsed named AST edits. Assert intended public
exports and review the exact diff before combining modules. Avoid shared stale file variables.

---

## ERROR-061 — Artifact ancestry was omitted from source eligibility

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed and independently rechecked
**Found by:** independent012 ACL/classification/head and missing-origin probes
**Affected files:** `brain/artifact_input_support.py`, `brain/artifact_input_sql.py`,
`brain/retrieval_sql.py`, `brain/artifact_store.py`, complete reference/contributor readers

### What happened
The initial new artifact byte reader traversed input ancestry, but source search eligibility
could omit the same parent's own private source. A readable legacy input leaf without a
source/derivation origin could also borrow the output's unrelated supported source.

### Root cause
Byte and SQL source selection used different dependency closures. Origin validation was
not enforced at every leaf of the new artifact graph.

### Fix applied
Source dependencies now traverse all ancestor artifact sources/derivation evidence and
resources before ranking/counts/handles. Stronger input classifications propagate. Both
native closure and SQL predicates reject unsupported source-free leaves. Six unchanged
independent probes pass35.19s; Root's existing Brain regression17PG passes103.84s.

### Prevention
Retain source search and actual byte/reference probes for ACL revocation, source head
changes, stronger classification, missing origins and cycles. A supported output source
cannot replace an input's own proof of origin or permissions.

---


## ERROR-060 — Model price expired after preparation and before final intent

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed and independently rechecked
**Found by:** independent current-price expiry during managed effect preparation
**Affected files:** `execution/intent_checks.py`, `execution/effect_store.py`, `harness/model_intent.py`, retained managed price test

### What happened
An immutable declared price was valid at the initial native model gate. Awaited
management checks crossed its deadline; the final generic authority check did not
recheck model price/health/evaluation windows, and the offline mock wire issued.
The original probe retains an actual wire timestamp after the declared expiry.

### Root cause
Model quotation and temporal qualification used the initial database clock; the
later effect clock covered only generic versions/lease/action authority.

### Fix applied
The model gate retains its exact pre-consumption policy. A pure final-clock hook
rechecks exact model qualification and quote after intent flush, along with the
execute lease. Composite hooks forward that check without repeating estimation,
database reads or provider calls. Expiry rolls back intent/counter writes and
keeps the existing held cost.

### Prevention
Original unchanged independent price probe1PG6.83s passes with no wire; normal
three gateway modes independently pass3PG11.71s. Retained combined4PG11.95s
asserts zero intent/attempt/new billing on expired price. Original gateway45unit/PG33.22s passes on the frozen source snapshot after this
fix; no live call is claimed.

---

## ERROR-059 — Acceptance omitted input grant expiry at the final write boundary

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed and independently rechecked
**Found by:** root independent restricted-PG commit probe
**Affected files:** `management/acceptance_store.py`, retained acceptance final-grant test

### What happened
A legitimate verifier grant on the report's supporting source remained valid
during input preparation and final revalidation. It expired during an awaited
outbox write; independent acceptance still committed. The original isolated
probe failed with DID NOT RAISE.

### Root cause
Final timed permission checks covered the protected result artifact's contributors
but omitted the complete contributor snapshots of each actual input artifact.
The company mutex prevents concurrent changes and does not stop time-only expiry.

### Fix applied
The final check covers the protected result and every prepared input artifact's
complete contributors, alongside registered freshness and the actual execute
lease. A denial rolls back acceptance, proof and outbox writes without changing
already-issued M1 receipts, counters or billing.

### Prevention
The unchanged original separate-database probe now passes1PG8.83s. Retained probe
and complete publisher integrity/native matrix28pass96.41s; scoped strict6/lint
pass. Exact replay also refreshes clock/lease/all prepared timed grants after awaited
lookup before returning the retained record. Original replay probe1PG14.57s
passes, preserving the immutable original record; retained replay/final-grant/
publication7PG47.29s. Preserve original C freeze as historical before root deltas.

---

## ERROR-058 — Goal publication reused permissions after final awaited proof

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed
**Found by:** independent M3-A restricted-PG final source-grant expiry probe
**Affected files:** `management/goal_store.py`, retained goal expiry integration test

### What happened
A legitimate owner source grant expired after awaited final handle validation;
the fresh clock checked source TTL only, so a known-baseline goal still committed.

### Root cause
Complete contributor grant snapshots were not reread at the final return/commit
boundary. CompanyControl serializes writes but does not stop time-only expiry.

### Fix applied
Recheck every contributor at fresh database clocks, compare exact grant snapshots
and deny final expiry before accepting source proof. All writes roll back.

### Prevention
Original independent probe passes1/4.48s after failure. Retained expiry plus20
owner/goal regressions pass21/26.55s; no goal revision/head survives the denied
publication. Scoped checks and evidence retain the original failure.

---

## ERROR-057 — Replacing revoked management documents implicitly reactivated them

**Date:** 2026-10-14
**Severity:** high
**Status:** fixed
**Found by:** current-owner store negative PostgreSQL probes
**Affected files:** `management/control_store.py`, `management/goal_store.py`, controls/goals tests

### What happened
Publishing a new mandate, charter or goal version set its existing revoked head
active again. Inactive mandate replacement could also apply new operating caps.

### Root cause
New publication and explicit current-head reactivation used the same state write.

### Fix applied
Preserve existing head activity on replacement. Inactive mandate publication
leaves actual M1 caps untouched; explicit exact-current reactivation applies its
saved caps in the audited owner transaction. Historical replay restores nothing.

### Prevention
Original2control and1goal failures are retained; the final20restricted-PG suite
passes31.82s with92.7%411statement coverage, strict7/lint/format. Holds/spend/
counters and policy/price versions stay intact; no live authority is activated.

---

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
*Next error ID: ERROR-180*
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
