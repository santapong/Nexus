# Current cycle family reader — source checkpoint

Checked 2026-10-15. The shared locked family reader is implemented and verified;
presentation/support publication and the operating release remain open.

The current-plan and complete registered-family checks now have a descriptive
entry point, `read_current_cycle_family_locked`, returning the actual PlanRevision
for one exact configured child. It retains company-first locking, current actor
scope, owner-approved full head2, original revision event, all twelve directory and
execution rows, registration hashes, permanent allocation and attempt quotas.
The four extracted row-check helpers are AST-identical to the previous source.

The native wrapper separately retains its closed E/EV/sender membership and zero
model limit, usage and delegation. Presentation, presentation verifier, support
and support verifier still fail that wrapper, including the zero-model verifiers.
The procedure root cannot use the descriptive child reader. No role flag,
permission DTO, schema change or new active tool route was added.

Validation:

- Five test-first failures established the missing seam. After implementation,
  44 focused tests and 264 compatibility tests pass.
- **3,758 unit tests pass in 80.76 seconds**, with 19 existing warnings, using
  the exact release source snapshot. Configured strict typing and both Ruff
  checks pass for all three changed Python files.
- Independent file review verifies the three held file pins, unchanged extracted
  helpers and retained native exclusions. Reviewer performed no runtime action.
- The initial primary-checkout run included a preserved untracked scope probe and
  failed its empty-URL case (1 failed, 3,771 passed). That local work remains
  untouched; its log is retained separately from the exact release-source result.

Source snapshot: `/home/santapong/.codex/nexus-cycle-family-integrated-20261015-1`.
Manifest: `4cdcb23475117b71d4cd29049eabcdb37b4dc6951525b73f70ceec02c1b67c09`.
Peer: `061541cb1d3061ec11ab7101b8221c9f5dd1fb2ae64de4111ce0a999e50a005d`.
Logs and Root receipt: `stockflow/cycle-neutral-seam-*` in the dated implementation
evidence directory. This source milestone does not qualify a new SQL lineage,
P/C engineering prerequisite reader, native publication or real builder job.
