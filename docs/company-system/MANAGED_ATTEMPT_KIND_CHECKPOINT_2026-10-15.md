# Managed actions retain the correct attempt budget — 2026-10-15

Managed non-model actions now require `tool_attempts`. The governed
`model.request.v1` branch retains its existing model-profile and ABI checks.

Previously, a valid generic artifact-write proposal passed `validate_plan_action`
when labelled `model_requests`. The real validator reproduction failed with
`DID NOT RAISE` in1.13 seconds. Native builder/notification checks covered their own
specialized roles, while the generic tool branch lacked the inverse kind check.

The two-line guard follows the unchanged model branch's return and precedes generic
cycle/tool validation. `EffectStore.begin` already calls managed validation before
moving a hold or reserving an attempt, so a mismatched managed action is rejected
before those mutations. This pure/source evidence does not claim an actual SQL
counter-mutation qualification.

Validation:9 focused tests pass in1.08 seconds, including the existing legitimate
model-request case; **3,814 unit tests pass in67.05 seconds**, with19 existing
warnings. Configured strict typing and both Ruff checks pass for the two changed
files. Independent file review confirms the exact two-file delta, unchanged model
branch and validation ordering. All1,588 primary release-source files match the
passing isolated snapshot; preserved unfinished local probes remain untouched.

Evidence root: `/mnt/data/nexus-implementation-evidence-2026-10-14/stockflow/`.
Source manifest `ae87338eba3fbf7bc10f7459195bf549368628265fe24c46aa642f00aa92af3e`;
peer `8b107965d586efd8f76e89120e3c95b2f0a5659b2c63197cb5936b6bb7e97f62`;
Root `managed-attempt-kind-root-integration-1.json` pins the red, green and full logs.
No schema, provider, native job, publication route or service was activated.
