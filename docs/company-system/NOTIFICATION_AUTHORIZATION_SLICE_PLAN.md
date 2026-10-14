# Exact approved notification authorization

Date:2026-10-14. Scope: one existing native owner sender and a process-local
verified credential; no approval issuance, provider request, new work or timer.

Root will add a focused notification worker authorization function that composes
ManagedNotificationPreparation's current native admission with the existing
authorize_registered_pending_locked primitive. The input is a trusted preparation
service, exact NativeNotificationSelection, expected RunBinding and verified
AuthenticatedWorkerIdentity. The caller cannot supply owner role, approval, clock,
body, recipient, callback or current-state flags. Constructor services retain the
configured catalog/policy/resource map. Defaults and API auth remain unchanged.

Under one actual CompanyControl transaction, require witness identity equal to
the expected actor/workspace, current owner membership and exact native current
binding. Resolve the existing prepared pending action from deterministic
notification_action_id(plan,sender,draft). Recompute actual draft/action/source/
target/profile admission before consuming the existing exact owner decision.
Call public registered authorization, flush, then rederive current admission,
approval/resources and final DB clock. Check captured source/recipient/profile/
approval/credential windows after the last await. Any unissued failure rolls back
new consumption and reservations; an existing replay must remain current and
cannot reset counters or cost. Return descriptive ActionRecord only.

No model or provider call exists in this function. It cannot approve itself or
expand standing permissions. Already-issued execution belongs to the separately
reviewed worker/reconciliation path. Do not use an already-consumed authorization
to bypass a changed source or expired credential.

Proposed file: notifications/worker_authorization.py. Tests use a new exclusively
assigned normal015 app-role fixture with actual public native source/draft/plan,
synthetic signed credential and exact owner decision. Required negatives: missing/
wrong/expired decision, role/source/pause/target/plan change, credential expiry
during actual hold/flush/revalidation, replay after source revocation and unknown
native effect. Preserve actual registered slices, no arbitrary raw operative rows.
Estimate: one focused implementation/integration slice after credentialed dispatch
fixture is stable; this plan is not execution evidence.
