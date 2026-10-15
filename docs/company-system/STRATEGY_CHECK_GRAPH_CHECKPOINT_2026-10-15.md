# Exact strategy check graph and acceptance descriptions

The internal C writer appends one protected strategy-check artifact, derivation,
complete artifact/source/evidence/resource input edges and its event in the
caller's transaction. Replay compares all original fields and every complete
edge group with expected+1 bounds, including original graph time and deterministic
event identity. It cannot authorize an action, commit independently, record a
receipt or accept work. The concrete publisher must first prove the actual issued
SV intent, current pair, source/READ/privacy/profile/lease/credential and clocks.

The pure acceptance builder compares the actual-described verifier receipt/action
pins against recomputed full check production identity and exact result bytes.
Stable target/proof IDs and mechanical-only limitations are preserved. Returning
this WorkAcceptance description grants no native persistence or permission; the
real store must obtain receipt facts and protected material itself.

Independent review found two missing exact replay relationships: derivation time
was not bound to original artifact/event time and event ID was not checked against
the writer's UUID5 identity. Both nominees failed DID NOT RAISE before correction.
The original fixture's arbitrary event ID was corrected to the actual writer
recipe; no production record was altered.

Final source5 freeze2:
`/home/santapong/.codex/nexus-strategy-verifier-receipt-20261015/ACCEPTANCE_ROWS_FREEZE_2.json`,
SHA `6090822d9a0162284886426b9084cb799224d509ca268105d1d4f371391aade7`.
32 pure/mocked row/description checks pass; six additional mocked C-store flow
checks are separate in-progress scope. Strict/Ruff/format5 and independent final
review pass. A fresh exactffc54b5 archive plus only these five files passes
2,953unit/33.43s with19 existing warnings. Evidence is in
`/home/santapong/.codex/nexus-strategy-check-rows-integration-20261015`.

The original graph negatives remain in `check_graph_original_red.log`. All
qualification here is source/pure/mocked, with no PostgreSQL, actual publisher,
source renewal, model, worker or acceptance write. B/S reader/store, C actor/store,
native acceptance and actual supervised-cycle qualification remain separate.
