# Current observations at the governed model gateway

Implemented bounded package, 2026-10-14, after Root's ABI acknowledgement.
The original ModelRegistry, endpoint/capability/data/price
fields, registry revision, registered Work and exact action/request IDs stay
unchanged. This adds no model/provider discovery, paid invocation, activation,
dependency, schema or work acceptance.

## Trusted configuration and resolution

Append keyword-only `model_observations: tuple[ModelEligibilityObservation,...]=()`
to CompanyModelAdapters, ModelIntentCheck, PersistentModelCallAuthorizer and
GovernedModelClient. It is server constructor configuration only; request/action
DTOs gain no observation or authority fields. Reuse public complete-tuple
validation and effective_model_registration; unknown/duplicate/spliced/future/
stale/negative current observations deny without old-positive fallback. Only
health/evaluations are projected temporarily for routing; the stored original
registry is never replaced or relabeled.

The governed client verifies its exact original registry + observation tuple
against its actual persistent gate before constructing the adapter. Managed gate
configuration must also match ManagementExecutionServices.catalog models and
observations. This prevents plan and wire paths from silently selecting different
fresh observations. Pure routing receives an optional default-empty observation
tuple and returns an effective model under the original revision.

## Intent and pre-SDK boundary

ModelIntentCheck resolves the exact selected observation, preserves the original
registration, and uses the same tuple at initial routing and its existing final
pure DB-clock check after real intent flush. The input estimator runs once.

New trusted pre-SDK protocol:
`await revalidate_before_sdk(request, quote, eligibility_sha256: str|None)->datetime`.
The adapter invokes this callback after SDK context setup and immediately before
the actual request. A real persistent gate re-reads current actor/lease/native
intent/action/source and managed admission under CompanyControl, preserving its
prepared pre-consumption policy, then compares the exact selected observation
pin/model/quote at the final fresh DB clock. No effect/counter/hold is created by
revalidation. Explicit observed adapters require this trusted hook; legacy
default-empty standalone adapter fixtures remain compatible. GovernedModelClient
always wires the actual gate hook.

The new server-only `ManagedModelDeadlineSnapshot(deadlines, children)` captures
the actual approved plan's exact child/charter actor and verifier grant pairs,
their current source heads, and the signed actor's complete dependency/proof/
author-output resource and artifact closure. Collection is bounded and denies an
unrepresentable closure. It does not create a synthetic verifier identity or read
unrelated grants. `require_managed_model_time(snapshot, catalog, now)` compares
every captured deadline and delegates each actual child to the public profile
predicate at the last DB clock, preserving the catalog's ANY-current-model rule.

Denial before intent stays not_issued. Denial after a committed intent has no SDK
request and returns an explicit failed/unknown result for protected recording and
existing unknown-hold handling; it cannot reissue or refund the consumed attempt.
Already-issued terminal results remain recordable after eligibility expiry or
revocation. Their evidence is not subjected to a fresh-execution qualification.
Receipt/cost mutation retains existing actual lease/fence/reconciliation rules.
In particular, a postcommit membership revocation preserves the protected server
result/evidence, unresolved native intent, consumed attempt and held amount. The
existing membership rule can reject ledger recording and lease release; the
client reports that recording/release is unconfirmed rather than refunding or
claiming a native receipt.

## Protected provenance and compatibility

Add `eligibility_provenance: ModelEligibilityProvenance|None` to ModelEvidence,
excluded from Python and JSON serialization when None. Existing `model` remains
the original immutable registration. New provenance records its canonical SHA,
the exact current observation (including original pins/receipt SHA/dates), and
its canonical SHA. `ModelEligibilityProvenance.sha256` is the computed selection
pin compared across intent and SDK checks. Validate these structural bindings without turning
decoded provenance into permission or requiring current freshness during later
result recording. Original endpoint/capabilities/classification/price remain
available for SDK usage reconciliation at the actual intent billing clock.

Captured fixed old evidence/request/registry codecs before edits; default-empty
wire/JSON/canonical SHA remain exact. The exact JSON comparison instantiates the
captured committed old class and new class from identical typed nested values;
the existing frozenset ordering of a separately parsed fixture is not changed.
New pure helpers/protocol/provenance and pre-SDK support stay in small new modules.
Approved narrow deltas are routing,
adapters, model_intent, model_authorizer, model_client and model_evidence; no shared
model request/permit DTO or schema changed.

## Focused proof

Tests first: old codec goldens; original byte identity with a fresh effective
observation; wrong company/revision/registration/hash/profile/duplicate pins;
current unhealthy/stale/future/absent evaluation denies; mismatched client/gate/
managed tuples deny; old unavailable price and capability constraints stay denied.
Dedicated restricted normal015 DB used: native approved Work + exact action,
real intent flush crossing observation expiry, postcommit/pre-SDK expiry or source
revocation with zero mock HTTP calls and conserved attempt/hold, one current
managed actual SDK mock response with protected evidence/native receipt/cost,
unknown timeout/no reissue, and issued result saved after observation expiry.
These are gateway/billing fixtures, not WorkAcceptance or live provider evidence.

Final coherent receipt: 25 checks passed in 100.55 seconds, comprising 12 actual
restricted PostgreSQL cases and 13 new unit cases. Strict types, Ruff and format
checks passed over 20 explicit Python files; all ten runtime modules are below
300 lines and their routines are at most 50 lines. The dedicated database was
returned to normal base with zero version rows and zero company tables. Exact
source, dependency and receipt hashes are in the package handoff under
`/mnt/data/nexus-implementation-evidence-2026-10-14/model-gate/observation-gateway/`.
Root owns subsequent native-profile integration and combined regression.
