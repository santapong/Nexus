# Owner controls checkpoint

The actual company app now mounts the signed-current-owner permanent work stop
and control descriptor. Company overview has pause/resume; work detail has an
explicit permanent-stop reason and confirmation. Unknown responses preserve the
exact command for retry. Resume preserves cancellations and issued results,
unknown cost reservations and permanent allowances. Default configuration is
still absent; the explicitly disposable pilot composes the cancellation store.

## Validation

An isolated copy of committed `8b93bec` plus the ten changed Python files passed
all1,093unit tests in15.07s with19 existing warnings. Ruff/format pass and strict
typing covers the nine control/API/test files and pilot composition. Root's
actual mounted factory passes15 restricted PostgreSQL HTTP cases under normal013
in48.52s; the worker's original normal012 freeze passed31checks, including16unit
and15PG, before mounting. JSON/YAML runtime schema equality and exact control
response serialization pass. Targeted original failure receipts are retained.

The final frontend TypeScript/build passes in5.51s;4client identity-race cases
pass. Visible Brave simulation of the actual components verifies initial
disabled cancellation, reason/confirmation, separate pause/resume, locked retry
inputs and byte-identical cancellation requests after a synthetic uncertain
response. The simulation contains no credentials and sends no real company
request. Screenshot and exact request evidence are in
`/mnt/data/nexus-implementation-evidence-2026-10-14/control-preview-*`.

Source snapshot/overlay SHA manifest:
`/mnt/data/nexus-implementation-evidence-2026-10-14/control-checkpoint-source.json`.
Worker freeze/handoff:
`/mnt/data/nexus-implementation-evidence-2026-10-14/management-control-api/`.
The additional CI group is configured; remote CI has not been run.

## Remaining release work

Owner browser acceptance awaits the human password/sign-in handoff. The live UAT
process was not restarted while that page is human-held; new pilot composition
will load on its next coordinated restart. Metrics and native operating
preparation and bounded builder are separate active packages. No model/provider,
timer/worker, external notification, Pi mutation or release deployment starts
from this checkpoint, and the supervised release goal remains incomplete.
