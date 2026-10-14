# Engineering immediate restart recovery gate

Date:2026-10-15. Proposed; code is unchanged. This is an open supervised-release
recovery gate, separate from the completed five explicitly sequenced fixture cases.

All five actual OS controllers killed/waited their recorded worker, then manually
waited for its actual ten-second native lease to expire before restarting the same
workflow. Those receipts prove that sequence and no second effect, but do not prove
an immediate worker restart can automatically reacquire a still-live old lease.
Current prepare_engineering_context invokes recover_dispatched once. A restart
before the old valid lease expires can throw; its non-retrying DBOS step may record
a failure before a recoverable native lease becomes available. Do not reset stored
workflows, alter old leases or relabel manual-wait evidence as automatic recovery.

Propose an engineering-specific helper:
`recover_engineering_lease(services, scope, authenticated, command) -> ExecutionLease`.
It follows the existing native_report_context.recover_lease pattern while retaining
the sealed authenticated credential witness. Bound the wait to310seconds, covering
M1's actual maximum300second lease plus observation margin; use a server monotonic
deadline and bounded asynchronous wait intervals. Always retry only acquisition of
the exact same permanently dispatched segment/action/run/workflow. No effect begin,
model/tool invocation, new intent/hold/attempt, new segment or allowance is retried.

On ExecutionDeniedError, inspect current native ExecutionSnapshot under the same
current signed actor and company scope. Continue waiting only when the exact same
segment retains the prior worker's still-live lease and all relevant authority
allows known-issuance recovery. A missing/released worker, foreign/different segment,
revoked principal, incompatible registration, cancelled fresh action or exhausted
wait denies rather than hiding a permanent error. Recheck the actual credential
window against a fresh database clock after each await and before returning the new
fenced lease. Never mint/refresh a credential or extend an old lease by assumption.
Cancellation propagates and no second worker or effect starts. Any actually acquired
lease must be returned to context or released on subsequent context failure, as the
current context cleanup regression already enforces.

Preserve policy separation: an already issued unknown result can be reconciled as
historical unknown without new source-derived publication; new protected proof or
acceptance still requires current unpaused active actor/source/governance/READ and
final clocks. A newly dispatched unissued effect cannot use known-recovery exceptions
or a cached receipt to bypass current approval, source, quota or cost checks.

Required immediate-restart tests use NEW exact disposable DBs/workflow occurrences.
For an actual OS death just after committed intent, launch the same workflow
immediately after kill/wait while the old native lease is demonstrably still live.
Observe the bounded acquisition wait on the same process/handle, then its actual
new fence, original unknown intent/one consumed tool attempt/positive unknown hold,
zero containers and released capacity. A known result/receipt occurrence also
restarts immediately, waits without caching failure, and returns current protected
acceptance without another container. Preserve actual DBOS workflow status/input,
source/credential deadlines, parent quotas and receipt/artifact hashes. A timeout,
credential expiry, principal revoke, different segment and cancellation during wait
must terminate without a new effect and preserve the original native facts.

Root reviews the helper and actual negative/positive test packet before implementation
or any new process run. Existing retained process databases remain unchanged. This
gate does not qualify StockFlow full regression, ARM64, service RTO or deployment.
