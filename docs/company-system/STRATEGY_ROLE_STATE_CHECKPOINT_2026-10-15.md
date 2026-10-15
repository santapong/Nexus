# Strategy role and fresh-publication state dependencies

Two strategy-only helpers now provide closed entry predicates. The application
role check requires the caller's active transaction and reads actual current_user
rolsuper/rolbypassrls with a fixed same-session SELECT. Only literalFalse passes;
missing, privileged or wrong-typed results deny. It changes no connection, role,
factory or generic runtime behavior.

The fresh-publication state helper permits an original pending intent with no
receipt, or an exact known succeeded single-output receipt when its output rows
already exist. Failed/unknown effects always deny; succeeded effects without rows
deny. It cannot convert saved bytes into a new success or create a recovery permit.
Fresh publishing remains same-fence; future recovery is a separate reviewed path.

Four-file source freeze:
`/home/santapong/.codex/nexus-strategy-verifier-receipt-20261015/ROLE_STATE_FREEZE_1.json`,
SHA `f4cc6fe403a660c41dc3ceba9e10793e2356a586c2f9f397a96bab4ff0b1be7b`.
14 pure/mocked focused checks/1.39s, strict/Ruff4 and independent eight-pin source
review pass. Concrete reader tests separately reproduced an unknown/failed actor
state omission (two original DID NOT RAISE cases) and a privileged-reader omission
(one original DID NOT RAISE case). Their corrected reader integration and full
qualification belong to the pending native publication source freeze.

No SQL, database, role change, effect, native publication or worker ran in these
helper checks. These helpers must be invoked by actual native reader/store entry
points; presence of their source alone does not establish integration or release.
