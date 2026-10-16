# Nexus — current product progress

Checked2026-10-16, Asia/Bangkok. **Nexus is the sole delivery target.** The owner
requested a faster workflow after approximately three days. StockFlow is an
optional later test project, outside the release critical path.

Active plan: [Nexus-focused delivery](NEXUS_FOCUSED_DELIVERY_PLAN_2026-10-16.md).
The supervised release is incomplete; default native execution stays off.

| Capability | Current state | Next observable result |
| --- | --- | --- |
| Architecture, contracts and governance | Implemented; scoped PostgreSQL/DBOS approval, budget and recovery acceptance passed | Current integrated operating profile and real usage |
| Company Brain | Backend/offline acceptance passed29/30 with all critical cases; three committed Nexus documents now ingested in a running local preview | Verify actual search and source citations in the signed-in browser; genuine LLM quality remains open |
| Management and owner interface | Real Today, Overview, Plan, Work, Approval and Report pages exist; Knowledge navigation and goal creation are implemented | Verify saved goal visibility, then connect the same goal to proposed work and reporting |
| Knowledge → goal UI | **Implemented and source-checked; browser acceptance pending** | Sign in, search, inspect a citation, save a goal and confirm it in the company view |
| Management-generated planning | **In progress**; governed historical-candidate consumer integrated and source-checked, but no connected owner planner | Connect owner/runtime preparation and formal proposal presentation with current goal/head checks |
| Genuine model operation | Whole-input bounds and separate qualification service/client integrated; actual restricted-PG/SDK-mock path passes | Owner/runtime wiring, concrete live conformance packet and representative quality; models remain disabled |
| Strategy, presentation and support | Components and scoped proofs exist; some earlier integration is domain-specific | Nexus-owned outputs with current evidence and role-specific acceptance |
| Bounded builder | **Blocked from activation**; diagnostics source patch checked and independently reviewed | Qualify current fault cases and a representative Nexus build with retained original-failure diagnostics |
| Notifications and reporting | Durable/offline recovery pieces verified | Real same-goal owner report/inbox and configured delivery/reconciliation |
| Private deployment and recovery | **Not qualified** | Pi setup/ARM64, independent restore, private access, rollback and24-hour soak |

## Latest actual result

The local frontend is running at <http://127.0.0.1:5188/company/login> with the
backend on loopback port9188. A fresh, isolated preview uses the normal company
migrations and public services to load three exact Nexus documents from commit
`4b581f1`. Its owner mandate permits goal creation. No goals, plans, work or
successful outcomes were seeded. Models, providers, queue workers and native
execution remain off.

The new Knowledge page calls the real authenticated Brain and management APIs.
It displays source excerpts, dates, freshness and provenance, then saves a cited
goal with an explicitly unknown baseline. Ordinary access refresh preserves the
draft while pausing mutations. Source-policy review caught and fixed a mismatch:
current citations with unknown freshness are allowed with a warning, matching
GoalStore; stale or historical sources remain blocked.

Focused frontend checks, TypeScript and production build pass. The backend's13
focused preview/configuration tests and strict/lint/format checks pass. The latest
integrated unit run passes all4,588 tests in132.45s with no failures or skips,
including the model/planning/qualification cases. Strict typing and Ruff
check/format pass for all31 changed Python paths. It uses fresh private non-home
temporary paths. The earlier path-related failure/recheck remains preserved in
ERROR-183; it is not retroactively relabeled. Source checks do not establish
browser acceptance. The visible Nexus sign-in page remains handed to the owner for
password entry, following the owner's browser-control preference.

A separate isolated API/database regression now passes the real chain: HTTP
signup/login → committed Nexus document search → materialized citation → the
frontend-shaped goal request → persisted goal in a fresh client's company view.
The baseline stays unknown and the desired day retains a null exact time. It uses
a synthetic test account in its own database; the owner's preview/invitation is
untouched. This proves the API/database journey, not the browser or owner UAT.
The goal overview also now displays desired date/precision/basis separately from
an exact deadline.

A fresh live check found both old preview processes absent after the handoff.
The same state was restored with detached local processes and private logs.
The later-turn check at04:05:48UTC confirms the same two PID/start identities and
HTTP200 from both services. This qualifies local turn survival; the old exit
cause remains unknown and production durability/24-hour soak remain unproven.

The management audit confirms a material product gap: PlanStore accepts a
caller-supplied plan, and the existing company worker is an offline TestModel
adapter. There is no connected production LLM planner yet. A server-built,
owner-approved planning-only plan can reuse current Work/model gates, but its
permanent root cannot be silently replaced by the current zero-model native
engineering root. The Nexus planning/native composition needs explicit
implementation while preserving the goal's original allowance and counters.

The integrated model package adds whole-input financial reservations, original
registry/model proof joins, a governed planning-result consumer and a separate
owner-approved qualification path. Real restricted-PG integration passes1test
in10.53s with the actual pinned SDKs over mock HTTP: both providers share one
permanent1USD/12-request Work; two known results settle and missing Google usage
retains an unknown0.478413USD hold. Three requests produce three attempts, replay
adds none, all leases release and the disabled/unknown models stay unqualified.
The absent-check denial also preserves the original work/hold/intent state.

Financial reservations do not prove prompt fit. Mock usage/costs are test-ledger
observations, not vendor invoices. Qualification does not enable a model, evaluate
company-task quality or complete work. The local preview still has an empty catalog.

The first actual current-V9 parent case then fails after one tool attempt:
`FaultSnapshot` validation rejects its observation record. The complete collector
report is retained, but the exact failing predicate and original candidate fields
were not saved. The outcome and USD0.010000 hold remain unknown/unbilled; its lease
is released. The wave is stopped; the other four actions remain unissued.
No parent-expiry, whole-tree retirement or current-V9 qualification pass is claimed.

The bounded diagnostics task finishes within its90-minute timebox: a separate
eight-file patch passes143 finite checks and independent source review. It adds
closed rejection reasons and a bounded, explicitly UNVALIDATED candidate while
preserving all original predicates, deadlines and worker ownership. It is held
outside the product checkout; no new native case has run and the original exact
failure remains unrecoverable. Complete the owner journey before another native
wave. Old frozen runs, actions, budgets and clocks stay preserved.

## Delivery sequence and time

A real local **Knowledge → cited evidence → saved Nexus goal → company view**
is ready for signed-in browser verification. The original1–2 focused working day
target included this integration and acceptance, which remain open. Saving a goal
does not create a plan or execute work. The following product milestone connects
that same goal through proposed plan, authorized work, verification and report.

| Outcome | Remaining effort forecast | Current limit |
| --- | --- | --- |
| Knowledge/goal browser acceptance | Up to half a focused day after sign-in handoff | Owner has the sign-in page |
| Governed model qualification and generated planning candidate | 2–4 focused-day budget from the revised plan, conditional on provider qualification | Database/SDK-mock checkpoint passed; owner/runtime bridge and live quality remain open |
| Same-goal plan/action/verification/report cycle | Re-estimate after representative builder qualification | Native builder gate unresolved |
| Full supervised release | No defensible committed date yet | Complete cycle, operations/recovery and24-hour soak still required |

These are remaining engineering effort budgets, with external waits separate.
The earlier6–20November range is historical. Do not restart the old1–2-day local
preview target: the preview/API slice exists and its browser acceptance is pending.

The approval→hold→intent→SDK-mock→protected evidence→receipt checkpoint passes.
Next connect owner/runtime preparation and the planning candidate to a reviewable
formal proposal. Root coordinates three bounded lanes: implementation,
actual integration and one combined boundary review. No new framework,
StockFlow feature or repeated builder wave is on that path. Focused checks run
during implementation; the full relevant regression runs once on the integrated
package. Next updates report a usable result or a concrete failing gate.

## Remaining release gates

One complete Nexus-owned operating cycle; current native fault/ARM64 qualification;
genuine configured models and US$5/day usage; owner browser UAT; notification
acceptance/delivery; private access, independent restore/RPO-RTO, rollback and soak.
Board-style oversight remains later: reviewed stable work and explicit promotion.
Automatic Meta Harness and dedicated graph infrastructure remain deferred.

Current Pi read-only evidence confirms disabled memory control and missing
rootless tools. Configuration/installation/reboot and live provider/email/deploy
steps need their concrete approved setup. Local password entry is the current
browser handoff; it does not authorize provider, email or deployment activation.

Detailed history: [release evidence index](RELEASE_GATES_CURRENT.md),
[actual setup and timing](CURRENT_V9_SETUP_AND_PARENT_AGE_CHECKPOINT_2026-10-16.md).
Actual stopped Source2 audit:
`/mnt/data/nexus-implementation-evidence-2026-10-14/stockflow/n-v9-source2-parent-failure-actual-file-audit-1.json`,
SHA6b8d9d9310518b5e625e8296d94ae76e858069c59ac40bf059dfb84df8618bb7.
The historical evidence directory name does not define the current product scope.

Current model-package evidence:
`/var/tmp/nexus-model-package-integration-20261016-1/UNIT_RESULT.json` and
`STATIC_RESULT.json`; actual PG receipt
`/var/tmp/nexus-model-qualification-pg-checks-20261016-1/WORKER_MODEL_QUALIFICATION_PG_RECEIPT_1.json`,
SHAa1a44d80c09a778ae7a0fb4c32083fb93ab6fb1155d0c5bba78f88285b95b728.
