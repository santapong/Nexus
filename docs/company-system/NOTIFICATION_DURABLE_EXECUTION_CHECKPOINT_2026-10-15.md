# Durable notification execution checkpoint

Checked 2026-10-15, implementation against a860b67/724ff1e. Six new execution
modules reconstruct the exact permanent command and current sealed owner identity,
acquire the same native segment, and describe actual body-free native history.
They are default disabled and have not launched a DBOS worker or made an HTTP call.

## Implemented boundaries

Fresh dispatch metadata requires actual PENDING on the fixed queue and exact
DBOS name/application/version/serialization/input. An issued original slot permits
terminal or queue-cleared history only with full immutable native bindings.
Any existing intent suppresses POST, including on an execute-mode lease. Recovery
waits only for the exact same live prior segment, with a 310-second total acquisition
bound and no credential renewal, new workflow, allowance or effect retry.

Known history checks current owner/member, sealed credential/configuration and lease.
It reads immutable draft pins without the private body. Succeeded receipt plus actual
UUID supports submitted even if the provider observation is absent. Failed receipts
collapse rejected and blocked: rejected requires an actual validated rejected
observation. Missing evidence stays explicit; billing remains unconfirmed/null.
Acquired leases are released on context or execution failure/cancellation.

The fixed worker uses one nonretry nexus.notification.effect.v1 step. Trusted startup
supplies the same bounded system engine to DBOS, requires exact explicit configured
endpoint/database/role, and checks actual restricted server and business backend
PID/start/client metadata while the business connection stays open. Source-level
startup tests mock those queries; actual engine/worker qualification is still pending.
Constructor failure leaves local
services unset, and an existing SDK singleton is denied.

## Review and validation

Freeze manifest phase3-durable-execution-freeze-1.json SHA
998a9a826c3e4a2130bbf3d388342396eccdd9cf80cb611bcebb1d2603824914 contains fourteen
source/test files and ten logs under the dated notifications evidence directory.
Root verified primary/private/staged file hashes and retained logs. Agent focused
69 tests/2.10s, strict fourteen files and Ruff check/format pass. Root independently
passed the same 69 tests/1.87s, strict fourteen files and combined 2,239 tests/22.36s
with nineteen existing warnings. This is freeze1 evidence before the endpoint amendment.

Independent review found and corrected two prelaunch gaps: only the business role
was checked despite a separate system URL, and fresh admission performed a later
clock read after closing source/approval windows. The current implementation passes
the same actual system engine and returns the already-qualified final clock.
Peer final review identified that database-name equality alone cannot establish
the same cluster at different endpoints. The original passing freeze is retained.
Freeze2 SHA63b55861c6da419d2c79edee1b16eb03bcd7f93278a87ae9970a98736947a8b1
adds configured endpoint comparison and the held business-backend witness. Agent
84 focused tests/2.27s, strict fourteen files and Ruff check/format pass. Root verified
all fourteen primary/private files and seven logs; actual SQL visibility is unproved.
Root changed-file strict checks and coherent 2,254 tests/22.88s pass with nineteen
existing warnings after the endpoint amendment.
These were source/mocked composition findings, not proved external-effect bypasses.
Unexpected programming/database exceptions now propagate after exact release;
only declared safe failures are described through real native history.

## Next actual proof

A separate frozen local package will use the assigned normal015/DBOS database,
public approval and atomic enqueue, genuine synthetic sealed credentials, SDK-driven
PENDING and MockTransport accepted/rejected/unknown outcomes. It must retain one POST,
tool1/model0, positive unknown cost and unchanged native replay. Actual OS barriers
and immediate restart follow separately. No real email, timer, billing, owner UAT,
deployment, ARM64, StockFlow or complete release claim follows from this checkpoint.

## First actual SDK run

Corrected test fixture freeze55100e4b and packetb3079e23 were independently reviewed
and launched once. The first accepted case reached SDK SUCCESS/submitted with one
mock POST, one native succeeded receipt, tool1/model0 and .01 unknown cost/null actual.
The full test FAILED16.66s at post-destroy asyncio.to_thread shutdown-evidence write;
native replay and rejected/unknown parameters were not reached. DBOS had installed
its now-closed executor as the adopted host loop's default (ERROR-100).

Original normal015 database and run tree remain, with no retry/reset. Terminal
receipt b251e99a retains the original log, portable output and safe native scalar
readback. Actual app backends are absent after the process exits; the failed fixture
did not export a complete in-process shutdown witness. Lifecycle correction and a
separately reviewed historical continuation are required before further execution.
