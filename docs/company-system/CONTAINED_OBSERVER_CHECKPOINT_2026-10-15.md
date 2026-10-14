# Contained observer and result binding checkpoint

Checked 2026-10-15 against31fe09b. The observer, actual read-only IO adapter and
immutable sidecar store are integrated as an unactivated implementation. Generated
filesystem/proc and fake engine tests qualify their mechanics; no payload job ran.

B2 freezecad1df52 retains ten files and twenty-one logs. Root independently passed
89 focused tests/1.44s, strict ten files and coherent2,331unit/23.06s. Independent
review verified hashes and corrected actual fdinfo mount/root identity, every-sample
revalidation, captured/current/retired identities, observed numeric limits/tree,
post-finalization clocks and pinned store root/pending bytes. A later narrow sample
post-CPU clock fix retains its original failing regression and the original freeze.

The result slice adds an optional containment ref excluded when absent. V1 rejects
new metadata and preserves existing goldens. V2 terminal output requires a ref.
Base result hash uses the existing canonical recipe with only containment=None;
full hash includes the ref. Actual sidecar reread checks original intent fence,
base result, method, spec/proposal, selector, image/name and observed status.
No later lease can replace original sidecar evidence. Five result/store tests,
strict/Ruff five changed files and coherent2,337unit/22.25s pass. Independent source
review verifies freezeeb663a13 and its logs. An early JSON-mode datetime hash mismatch
was corrected using the existing model-mode canonical recipe; original failure stays.

These descriptions do not enable runtime v2. Shared services/full-method pin,
current-source/parent final spawn ordering, protected publisher/engineering loader,
compatible receipt-bound cleanup and actual native M1/outer-timeout qualification
remain required. Kernel thread timeout cannot force-stop blocked filesystem IO;
short-lived descendants are not claimed exhaustively observed. Missing/raced/late
facts remain unproven. Full StockFlow and ARM64 remain separate release gates.
