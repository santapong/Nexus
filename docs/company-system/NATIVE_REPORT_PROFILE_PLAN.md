# Bounded native report operating profile

This profile prepares one pending native report/check pair from existing owner records. It starts no timer, queue, worker, model call, external send, provisioning operation or paid gateway. Exact owner approval remains required because the current standing-tool registry admits only the two fake internal adapters, not native report write/check.

## Existing owner records

The owner saves a native operating report with exact ReportSelection and a current commitment referencing the same approved plan and exactly its author/verifier pair. DueIntent retains source precision. Preparation is due only when an actual operator_explicit actionable_at is present and no later than fresh database time; an unknown or date-only source time never invents an instant.

`NativeReportPreparationService.resolve_profile(owner_scope, owner_identity, report_id, commitment_id, evidence_ids)` returns a typed descriptive profile reference. It binds the actual report and selection hashes, current commitment revision/hash and bounded ordered quote IDs. It is not a permit. No extra profile table or owner identity is manufactured.

## Pending actions

The constructor requires the actual native producer, server catalog, complete artifact reader, qualified registered source policies, configured authenticated actor resolver, current resource resolver and fixed write/check rules/cost policy. `prepare_author(profile_ref)` resolves the actual selected author and fully rederives native bytes/manifest before creating the pending write proposal. The action's durable parameters carry report ID, exact quote IDs and exact input/output/recipe hashes.

`prepare_verifier(profile_ref, actual_execute_lease, author_action_id)` requires the selected distinct verifier's actual execute lease and the actual successful original author receipt. It rederives native VerificationSpec/report/source/ledger/check inputs. Check parameters retain the exact author action selector and target/input/output/recipe hashes. This service neither acquires nor releases that lease; caller M1 lifecycle remains authoritative.

Stable action UUIDs derive from the immutable report ID and phase. Exact replay returns the same native journal fact, including an already recorded owner decision. A changed proposal cannot replace that action ID. A new owner-saved report occurrence can propose another action only within current approved work and remaining lifetime limits; no task/run/root/quota is created or reset here.

Current signed actor/work/plan/goal/charter/resource/cancellation/model qualification, full source/artifact closure and complete intended audience are checked under CompanyControl. Public submit_pending_locked appends the canonical awaiting_approval journal row in that same transaction. After the real flush, current admission is repeated and both captured source/grant/profile clocks are checked. The verifier's exact native lease deadline is also retained and checked after the final awaited protection, including exact replay. Pending append creates no approval, standing grant, authority consumption, cost hold, attempt, receipt, dispatch, artifact or acceptance.

## Journal compatibility

The helper is extracted from CompanyJournal.submit's existing append behavior. CompanyJournal.submit delegates to it inside its original company-scoped transaction. Exact canonical scope, pause/policy/price pins, immutable replay, pending state and absence of approval/consumption remain. Registered actor/governance/source admission belongs to the profile wrapper; a decoded reference or low-level helper does not authenticate a caller.

Root owns actual timer/profile activation, owner HTTP/UI selection, exact decision/authorization and scheduler/native worker composition. These modules alone are preparation infrastructure, not an activated daily company operating loop or business/live-provider acceptance.
