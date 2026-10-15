# Strategy verifier receipt and check output

The new read-only receipt gate binds the current execute lease and sealed signed
credential to actual verifier work, immutable journal action/proposal, original
succeeded tool intent, original lifetime attempt/fence, actual receipt and exact
strategy artifact identity/bytes/resource/derivation. It preserves an original
intent fence1 while the current lease is fence3; no attempt, hold or receipt is
rewritten. Final lease/credential clocks are checked after the last result lookup.

The check-output compiler separately binds the full actual-described target,
original S snapshot/output and supplied complete check manifest. The check action
input hash differs from the mechanical result's original S snapshot hash. Exact
deterministic check bytes are recomputed, so a supplied verdict/self-consistent
checksum cannot replace them. It does not resolve B linkage or native READ.

Independent review and Root reproduction found an initially missing chronology
relationship: actual artifact metadata could predate issuance or follow its
receipt. Two retained negatives failed DID NOT RAISE before correction. The gate
now requires original attempt<=intent<=publication metadata<=receipt<=final DB
clock, with journal authorization consumption no later than issuance.

Private source/evidence:
`/home/santapong/.codex/nexus-strategy-verifier-receipt-20261015`.
`SOURCE_FREEZE_1.json` SHA
`da16488d78f250c7932e610ea23c5ce685b716049ff41d35e43ee22bd42873c4`.
56 focused mocked-SQL/pure tests/1.24s, strict/Ruff/format5 pass. Coherent whole
suite passes2,921unit/32.68s with19 existing warnings. Independent final review
found no further material issue in this declared scope. The original chronology
red log and all pre-correction/static logs remain retained.

This is an unhooked source boundary. It establishes neither actual current S/SV
plan/pair/owner authority, source/protected READ, full result derivation graph,
actual mechanical verdict nor WorkAcceptance. A concrete trusted native reader
must supply the actual target and complete manifest, and acceptance must compare
the succeeded receipt's original input/output action pins with the recomputed
result. No database, provider, SDK, worker, model or acceptance publication ran.
See the [acceptance integration plan](STRATEGY_ACCEPTANCE_IMPLEMENTATION_PLAN_2026-10-15.md).
