# Owner native report and preparation API

Root exposes existing native stores under current signed-owner authorization.
New optional ManagementApiServices reports/preparation fields and a controller
allow saving a report snapshot, reading dated licensed history, resolving an
existing owner report/current commitment/evidence selection and preparing its
exact pending author. No route approves, consumes, claims, enqueues or executes.

The save endpoint explicitly creates a new snapshot; it has no automatic client
retry. Current native author/plan/selected task IDs and aware period labels go to
OperatingReportStore.save_snapshot. The native data expenses remain selected-work
lifetime, not a claimed interval calculation. No caller status/count/owner/actor
or budget is accepted. Profile preparation re-resolves the exact current owner
selection/commitment before using configured actual author identity; decoded
refs cannot bypass that lookup. Verifier preparation remains the loop's actual
claim/release operation, not a caller-supplied lease endpoint.

Files: new company_native_report_routes.py and real HTTP fixtures/tests; optional
service/factory/OpenAPI wiring. Explicit pilot composition comes after the
trusted identity/resource rules are concrete. Owner UI is a separate integration
gate, never inferred from router tests. No new database table/migration here.

Tests first on exclusive native_report_api DB: current owner/member/foreign/
inactive/signature/disabled gates; source-private dated denial; aware/exact/bounded
selection; actual stored profile to one pending author and exact replay; changed
ref/current source/plan/commitment/cancellation denies; issued budgets/counters/
receipts unchanged, no dispatch/effect/acceptance created. HTTP exceptions keep
their specific status despite Litestar ValueError ancestry. Focused types/schema
checks precede stable milestone regression and browser acceptance.

High risk: impersonation or false operation claims. The current owner can select
only actual pre-existing rows. The preparer resolves configured author identity
and checks current full native admission after awaits. Responses remain exact
pending journal facts with scheduled=false/executed=false/model_requests=0.
