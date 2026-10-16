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
| Strategy, presentation and support | Components and scoped proofs exist; some earlier integration is domain-specific | Nexus-owned outputs with current evidence and role-specific acceptance |
| Bounded builder | **Blocked from activation** | Resolve the collector's missing validation reason, then pass current fault and representative Nexus build gates |
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
focused preview/configuration tests and strict/lint/format checks pass. The full
unit run reports4,309 passed,1 skipped and5 temporary-path failures: the check
used an owner-home directory that the builder correctly rejects. Those exact5
cases pass with a fresh private temporary directory outside the owner home;
production guards are unchanged. This is a full run plus a focused corrected-path
recheck, not a single all-green full run. These source checks do not establish
browser acceptance. The visible Nexus sign-in page is handed to the owner for
password entry, following the owner's browser-control preference.

Current production backend repair passes4,307 unit tests at7acbb8b. The newer
private qualification source separately passes382 tests and strict/lint/format45.
Its fresh five-case setup completes0 in48.378s and passes independent file/SQL
joins. These are supporting checks, not full product completion.

The first actual current-V9 parent case then fails after one tool attempt:
`FaultSnapshot` validation rejects its observation record. The complete collector
report is retained, but the exact failing predicate and original candidate fields
were not saved. The outcome and USD0.010000 hold remain unknown/unbilled; its lease
is released. The wave is stopped; the other four actions remain unissued.
No parent-expiry, whole-tree retirement or current-V9 qualification pass is claimed.

The builder task now focuses on that exact observability gap before another run.
Brain, management and owner UI work continue in parallel. Old frozen runs,
actions, budgets and clocks stay preserved.

## What you should see next

A real local **Knowledge → cited evidence → saved Nexus goal → company view**
is ready for signed-in browser verification. The original1–2 focused working day
target included this integration and acceptance, which remain open. Saving a goal
does not create a plan or execute work. The following product milestone connects
that same goal through proposed plan, authorized work, verification and report.

The full release ETA will be re-estimated after that journey and a representative
Nexus builder run. The earlier6–20November date range is historical, low-confidence
planning context. There is no reliable committed finish date yet.

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
