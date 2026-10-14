# Native builder recovery guard review

Independent review reproduced a P1 disclosure error in the first local runtime
freeze. After revoking the actual actor's source READ, `run` denied cached data,
but direct `reconcile` could borrow a guard for the owner and return private
results/logs/artifacts. The original actual-PG probe failed in5.14s and remains
unchanged in `builder-review/test_reconcile_guard.py` and `reconcile-first.log`.

Both entry points now share exact spec, policy, lease binding, actual identity
and configured output-target qualification. The guard cannot replace the caller.
Recovery also checks actual current native action/work before saved-result reads;
existing M1 row, mode, identity and fence checks remain authoritative. The same
independent probe passes in4.84s. Its body is retained in the owned boundary
suite with only the fixture database ownership adapted.

The corrected normal company014 combined matrix passes74 tests in49.17s,
including62unit and12restricted-PG cases. The narrow source/test delta passes
strict types/lint/format. Original39-file freeze and failure evidence remain
historical; the new freeze references the independent verdict and corrected
source hashes. No independent reviewer database was modified by the implementer.

This closes the inspected recovery privacy boundary. The scoped review inspected
13 runtime boundaries and does not establish actual worker crash/restart,
representative StockFlow results, ARM64, engineering acceptance or full release.
Public dependency-cache and pnpm compatibility work remain separate preparations.
