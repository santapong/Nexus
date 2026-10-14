# Current model eligibility without replacing immutable registrations

Task: let an existing managed plan use newly checked model health/conformance
without rewriting its immutable model registry revision or original registrations.
The actual sibling-plan attempt denied when its original eligibility expired;
changing registry revision cannot preserve the existing registered children.

Files: new management/model_observations.py; plan_support.py catalog validation
and profile resolution; native_fact_admission.py and managed_sources.py retained
final deadlines; new focused unit tests. No schema, provider or automatic refresh.

Trusted explicit catalog configuration may supply at most32 observations, one per
exact model ID. Each pins company, immutable registry revision and full original
registration canonical SHA, a new observation ID and receipt SHA, fresh health and
profile evaluations. Only health/evaluation fields resolve from this separate
observation; endpoint, enabled state, capabilities, classification, price and
registration/binding identities remain original. Default empty field is excluded
from Python/JSON encoding to preserve old catalog SHA. Unknown/duplicate/mismatched
observations deny configuration. Future/stale/unhealthy/failed current observations
deny eligibility; they never fall back to older positive observations.

Tests first: exact old encoding/hash, immutable original unchanged, current explicit
positive observation, mismatched/company/duplicate registration denials, expired/
future/unhealthy/failed replacement, independent price/disabled/model-action pins,
and retained final deadlines. Actual offline TestModel check receipts remain a
separate worker deliverable; a declaration alone does not prove a check or live
provider quality. Routing/provider gateway observation integration stays separate
until it can carry the exact evidence and request identity; this change only
narrows existing managed native admission and captures matching final deadlines.

Done: focused type/lint/unit + actual same-parent fixture evidence prove refresh
without resetting children, quota, money or original outcomes. High risk is stale
or mismatched eligibility; mitigate with exact pins, negative checks and combined
boundary review before any private job. Current goal release gates remain open.
