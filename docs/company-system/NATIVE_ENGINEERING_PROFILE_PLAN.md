# Explicit model-free engineering admission

**Date:** 2026-10-14. **State:** proposed implementation; no admission or execution activated.

Task: admit owner-approved mechanical engineering and independent verification
through explicit server profiles, without manufacturing model health or quality.
Root owns the shared admission change. The engineering agent owns new acceptance
modules and harmless public-store fixtures. Existing StockFlow qualification work,
parent allowance, holds and revisions remain immutable.

## Profile interface

Add a bounded optional `native_profiles=()` constructor catalog field, excluded
when empty. A strict `NativeExecutionProfile` identifies company, exact original
model-catalog revision and `canonical_sha256(catalog.models)`, workflow name/version, execution profile
name, acceptance recipe, and exact permitted tool/version/resource tuples.
The initial closed profiles are `engineering.native.v1` with
`engineering.change/v1` and `verification.native.v1` with
`engineering.verify/v1`. These are mechanical execution identities. They never
enter `Profile`, model evaluations, model routing or provider requests.

Register a new catalog/procedure/goal for the CSV correctness objective. The
catalog may contain zero models; its existing pricebook must still equal current
CompanyControl. Do not replace an existing work registration or relabel the old
Nodev3 result. No database schema or existing request DTO changes are planned.

Eligibility selects one exact native tuple before the ordinary LLM branch. Missing,
duplicate, conflicting or partly matching tuple denies. Require exact company,
registry digest/revision, profile, workflow and zero model quota. Empty configuration
preserves current LLM behavior and serialized catalog bytes. Existing model
profiles retain their current genuine health/evaluation checks.

For the first native-only plan, require exactly one author/verifier pair with the
seven closed criteria and one matching verification edge. The non-executing
procedure binds `engineering.change/v1` and `engineering.native.v1`; it and every
child have zero model quota. Procedure execution remains denied. Check the actual
registered ancestry under CompanyControl at execute claim
and effect admission; every ancestor must have zero model limit/used/delegated.
Hard-deny `model_requests` and `model.request.v1`, even if a caller supplies a
different tool or kind. Native profiles cannot confer a general tool permission.
Each actual proposal must match the native tuple and the current charter/tool
catalog; its existing exact M1 approval, source rights, lease, policy, lifetime
attempt/USD slices and Bangkok daily budget remain mandatory.

The engineering publisher additionally checks the approved author/verifier edge,
seven closed criteria and `native-engineering-change-v1`. The builder composition
must bind the actual policy, image, command-recipe digest and output/patch scope
to that declaration. A native tuple is admission configuration, not evidence that
a process ran or a patch is correct. Generic report-only verification stays
unable to accept engineering work.

## Files and verification

Proposed new modules: management/native_execution_profiles.py and
execution/native_profile_checks.py. Narrow shared edits: plan_support.py,
model_profile_checks.py and management_checks.py. Optional catalog constructor
checks must validate the complete tuple rather than first-match selection.
No changes to provider clients, immutable registration fields, generic runner,
existing acceptance recipe or normal015 migrations are included.

Write negative tests first: default compatibility; empty model catalog allowed
only for exact configured native work; ordinary LLM work still denied; duplicated
or mismatched workflow/revision/digest/profile; nonzero child/procedure/ancestor;
model tool or attempt kind; unsupported tool/resource; revoked charter/member/
source; pause/expiry after awaited admission; exhausted lifetime slices; original
registration unchanged. Restricted normal015 fixtures must use actual owner
approval, current source access, native receipt and independent protected proof.

Done means a stable reviewed package passes focused units/types and actual PG
admission negatives, followed by one milestone regression. The later private CSV
job needs a separate exact packet and full module baseline/regression, patch,
independent run and recomputed acceptance. No paid provider, user account,
StockFlow checkout write, Pi change, release publication or business-readiness
claim follows from this plan.

Risk: high because profile admission is an authority boundary. Mitigation: closed
opt-in identities, zero model allowance throughout actual ancestry, exact native
tool pins, default compatibility, temporal negatives and independent integration
review. This proposal is not yet an implementation receipt.
