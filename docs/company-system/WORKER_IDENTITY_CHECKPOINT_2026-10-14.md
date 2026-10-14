# Verified process-local credential expiry

The new verifier accepts only an explicitly configured existing opaque credential
and strong signing key, with disabled default. It verifies actual HS256 signature,
required literal int iat/exp and UUID sub/workspace claims, rejects unsupported/
expired/future/overflow values, and retains only identity plus aware UTC dates.
Role/company claims are ignored. Current owner/member/work/effect checks remain
independent. It neither mints nor renews credentials or reads production settings.

AuthenticatedWorkerIdentity is a frozen process-only witness with no JSON/DBOS
encoder or public constructor. Its synchronous require_time checks the captured
window after an operation's last await. Binding equality checks actor/workspace;
it cannot grant a lease, approval, budget or provider call. The acquisition boundary
sanitizes errors and preserves cancellation; tokens are capped at16KiB.

The exact two-file freeze notifications/worker-identity-freeze-1.json SHA
231aaf65f31686d6e6fe5f149008cacd26c851dd94aee955bac79ce4d1251819 is under the
dated implementation evidence folder. Frozen46synthetic JWT cases pass1.74s,
strict/Ruff/format2files pass. Root reviewed exact hashes and separately ran84
identity/existing API auth cases in2.42s on the qualified local runtime. A prior
Root command named a missing auth test file and ran no tests; the corrected command
and original receipt are retained. No behavior or assertion was removed.

Next wrappers must carry this witness through final intent flush and nearest HTTP
issuance, retain current native draft/source/approval/member/lease rules and conserve
committed unknown intent/attempt/slot/hold on expiry. These hooks, actual durable
worker integration and real owner credential provisioning remain unverified by
this slice. All JWT issuance here is synthetic test code only; no user credential,
provider/email, database state, held UAT or Pi service was changed.
