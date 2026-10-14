# Native measured-goal observations — bounded implementation plan

Selected2026-10-14 after the M3 integration reconciliation. This plan adds no
migration, API/view wiring, timer, authority, budget, effect or goal-completion
permission. Root owns normal company013 and shared model registration.

The first registered recipe is `native.accepted-report-count.v1`, with exact unit
`count`. An actual current signed owner selects1..100 unique real tasks under one
exact current approved goal/plan revision and a declared metric. The service
resolves immutable native registration rather than accepting a count or verdict.
It uses the public `current_accepted_work` gate with the actual owner identity,
real persisted work, complete artifact reader and registered source freshness.
A counted task binds an actual company.report.write.v1 author action, exact
mechanical report criteria/recipe, successful receipt and native protected proof.
Absent acceptance or a raw candidate is not counted. A claimed passing result
whose current proof/source/ACL is unavailable becomes unknown, never known zero.
Unsupported recipe/unit produces unknown or denial rather than semantic inference.

ABI: `MetricStore(factory,catalog,artifacts,freshness).observe(owner_scope,identity,
MetricObservationRequest) -> MetricObservationRecord`; owner-only `get_saved` is
immutable dated history with required source visibility, while `current` freshly
rederives the recorded selection and returns known/unknown value and comparator.
Requests contain observation_id, exact GoalRevisionRef/PlanRevisionRef, metric_id
and bounded unique task_ids. They contain no count, completion, verdict or role.

An append-only observation envelope binds exact request, native selected work
hashes, independent acceptance/receipt/proof references, complete resource/source
freshness references, actual SourceTime precision, baseline and observedAt basis.
A known current count can be compared with the frozen target; unknown baseline
remains unknown and cannot be invented as zero or a measured delta. Missing
baseline source permission never exposes its protected value/date/evidence.
Fresh final DB clock covers every accumulated source/grant deadline after awaited
reads and writes. Replay preserves the original envelope/time; changed request
or operation identity cannot overwrite it, and revalidation never renews proof.

One proposed native table holds company/observation UUID, exact goal/plan revision
IDs, metric/recipe, request/snapshot hashes and exact JSON, known/unknown columns,
owner operation/audit identity and DB observedAt. Root supplies native FK/RLS/
immutability/index/check migration qualification. No new table is used until the
normal013 handshake on exclusive nexus_company_test_management_metrics.

Tests-first sequence: strict request/value/source/duplicate/replay contracts;
actual public report/check/acceptance fixture with declared metric recipe;
known count and absent/candidate zero; private/stale/expired proof unknown;
wrong owner/company/goal/plan/task/recipe/criteria; unknown baseline/comparator;
exact replay/history and late grant expiry. Actual fixtures use production
producer/validator/loader and public native publisher, not a caller-authored pass
or raw operative SQL seed. Then focused restricted-PG/static checks and a frozen
handoff before Root API/view integration. Existing M3 packages remain frozen.
