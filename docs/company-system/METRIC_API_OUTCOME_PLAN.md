# Metric API and owner outcome display

Task: expose the frozen native observation publisher and fresh current readings
through the actual signed owner API, then display them alongside an exact plan
and company goal. Existing metric runtime and normal013 remain the authority;
the API accepts no count, result, role, completion or new allowance.

Root changes optional ManagementApiServices, factory mounting, exact OpenAPI,
new metric controller/HTTP fixtures, and company frontend API/hooks/outcome
components. Worker owns a separate bounded current-page query contract/service
with current proof permission/freshness and aggregated final-clock deadlines.
No new migration is required beyond the tested normal013.

Tests first: actual signed owner POST/recorded/current API; immutable exact
replay; foreign/member/forged owner/current revocation; wrong company/ref/task;
literal audit IDs rather than caller authority; paused-safe audit and unchanged
issued history/cost/counters; private/stale proof becomes current unknown while
recorded licensed history denies; exact JSON/YAML current tuple/money shapes.
Use exclusive metrics_api database; query worker retains its own metrics DB.

POST observation accepts strict {request, operation_id, audit_trace_id}. Request
contains exact goal/plan refs, declared metric and1..100 selected native tasks.
GET current rederives native facts; GET recorded returns dated licensed history.
Current-page discovery uses company/goal scope, native date+UUID cursor and
max8 observations, with a30s timeout and2MiB serialized-page bound. All known
source/grant deadlines are checked after all awaited page reads. Unsupported,
private, inactive or stale projections retain unknown rather than leaking saved
facts or inventing zero. Cursor is pagination only.

UI uses actual generated schema types. An approved current plan and its exact
goal supply the observation request; the owner chooses declared metric and
bounded actual child tasks. The response is an observation, never a completion
button. Unknown baseline is shown explicitly; current checked time is separate
from original recorded time. Existing observations are discovered by the
bounded API, so refresh/browser restart does not lose the ledger.

Definition of done: real HTTP/native-store tests, focused types/lint, frontend
build and visible scoped simulation, then stable-source milestone regression.
High risk: source permission and misleading completion. Mitigation: no caller
values, current full native gates, aggregated final clock, clearly distinct
current/dated records and no authority/work/provider activation.
