# Nexus foundation validation — 2026-10-13

**Historical initial foundation slice.** Current integration evidence is in [governance validation](VALIDATION_GOVERNANCE_2026-10-13.md).

**Source:** `feature/company-foundation`, based on `6a8c8ef`, local uncommitted implementation. [Progress](PROGRESS.md), [roadmap](DELIVERY_ROADMAP.md), [migration inventory](MIGRATION_INVENTORY.md).

| Check | Result | Scope |
| --- | --- | --- |
| Existing baseline unit suite before edits | 225 passed, 25 warnings | Locked Python 3.12 environment |
| Initial-slice full unit suite | 275 passed, 25 warnings | Existing tests plus 50 new contract/policy/context/fixture cases |
| Focused foundation suite | 59 passed | 50 unit cases plus 9 real PostgreSQL cases |
| New-module coverage | 94.46% | Company/harness modules only; 80% threshold passes |
| Ruff lint/format | Pass | 225 Python files formatted, including migration 017 |
| Mypy | Pass, 224 source files | Repository strict configuration, CI missing-import setting |
| Migration/metadata | Pass | 017 alone, disposable PostgreSQL 17, each-case upgrade/downgrade |
| Company RLS/immutability | Pass | Restricted non-superuser DB role, missing context denied, snapshot edit rejected |
| Workflow YAML | Parses | New PostgreSQL 16 CI job prepared; no remote run claimed |
| Contract freeze | 13 JSON schemas | Wire shapes exported; semantic constraints remain in acceptance tests |
| Documentation/fixtures | 57 local links/anchors resolve; fixture JSON valid | New/changed Markdown references and frozen JSON assets |

The DB cases also prove pending decisions are committed before another session reads them, competing workers consume one approval/hold, concurrent tasks cannot over-allocate a day, pause survives a new service object, and unknown billing retains its hold until idempotent reconciliation.

The suite uses an explicitly separate test database and Unix socket. No existing PostgreSQL server, Pi service, production data or credential store is changed. No external action or paid model is executed. A new service object reading persistent state is not a process-kill/DBOS replay test.

Full-chain Alembic/data migration, authenticated API scope, provider/API-family conformance, DBOS version/replay, effect fencing/reconciliation, parent quotas, actual retrieval/prompt assembly, Pi ARM64/sandbox operation, browser acceptance, configured email and the full StockFlow operating cycle remain unverified. M0/M1 full gates and M2–M6 stay open.

Evidence directory: `/mnt/data/nexus-implementation-evidence-2026-10-13/`. Contract export digest is recorded in its `contracts-manifest.json`. The schema exporter and raw coverage are offline artifacts; no source/package release is implied.

## Reproduction and resume

Use the existing repository lockfile and Python 3.12; `uv sync --frozen --extra dev` prepares the environment. Unit command: `pytest nexus/tests/unit/ -q`. CI-style checks: `ruff check nexus/`, `ruff format --check nexus/`, and `mypy nexus/ --ignore-missing-imports` with the repository strict configuration.

For the journal suite, explicitly set `COMPANY_TEST_DATABASE_URL` through Settings to a disposable database named `nexus_company_test_*`, distinct from the application DB. Its admin connection applies migration 017; create a restricted login role named `nexus_company_app` with public-schema usage first. The fixture grants table privileges, tests as that non-superuser and downgrades the new schema after each case. Never point this fixture at a production or populated database. The new CI job documents the equivalent PostgreSQL 16 setup.

Run `pytest nexus/tests/unit/test_company_foundation.py nexus/tests/unit/test_company_context.py nexus/tests/integration/test_company_journal.py --cov=nexus.company --cov=nexus.harness --cov-fail-under=80`. The earlier isolated local cluster used PostgreSQL 17 and a private Unix socket under `/tmp/nexus-company-tests-2026-10-13`; it was stopped after validation. Recheck or recreate temporary resources before rerunning. No shared service restart is part of this procedure.
