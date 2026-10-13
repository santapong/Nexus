# Nexus governance integration validation — 2026-10-13

**Scope:** local `feature/company-foundation` based on `6a8c8ef`, updated through 2026-10-14. The original dated sections retain historical package evidence. The closure section below states current checks; the release goal is active.

## Closure evidence — 2026-10-14

The actual target environment and independent profile are unchanged in purpose. Company001–007 now installs **17 tables**, including lease-principal ownership and separate immutable billing evidence. Normal clean install/repeat/metadata/downgrade passes1 case; populated pre006 live-lease refusal/expired-lease fencing passes1 separate case. Existing merged legacy migration issues remain documented rather than repaired by this profile.

| Integrated package | Current executed result | Boundary |
| --- | --- | --- |
| Runtime/terminal/recovery |30 PostgreSQL cases; combined rerun30 in19.57s | Principal-bound fences, retained unknown charges, permanent dispatch, blocked state and terminal receipt handling |
| Registered authority/controls |Combined42 PostgreSQL in21.96s | Fresh owner/actor/ancestry and pause checks |
| Enqueue/effect-day |Combined12 PostgreSQL in14.79s | Atomic consumption/hold/source/dispatch/enqueue and actual-day cap |
| Actual offline worker |7 process cases under company006 | SIGKILL after intent/output/receipt; protected known output reused, missing output remains unknown; compatible-version integration still being added |
| Owner reconciliation |12 PostgreSQL/hook cases | Current owner records already-issued facts under a distinct principal; no new effect or business completion |
| Persistent model gate |52 checks:19 unit +33 PostgreSQL/offline SDK | Exact request/recipe/prices/input coverage before committed intent; protected output and actual/unknown billing afterward |
| Owner billing |17 PostgreSQL cases,94% scoped coverage | Original price version and protected immutable invoice evidence; no receipt/state/counter rewrite |
| Whole unit before client wrapper |692 passed,19 existing warnings,53.86s | Explicitly excluded the unfinished model-client module; not final whole-tree acceptance |

Per-package evidence: `/mnt/data/nexus-implementation-evidence-2026-10-14/model-gate/`, `owner-billing-work.md`, `whole-unit-preclient.log`, and `combined-*.log`. Earlier worker evidence remains in the2026-10-13 folder. Counts overlap and are not summed. Test-file typing followups preserve security assertions; their later hashes do not silently replace historical executed manifests.

The governed client wrapper and combined independent M1 review are being finished. No production estimator, enabled live catalog/price card, paid provider request, vendor billing resolver, new HTTP execution intake or company completion publisher is claimed. Worker output remains a verifying/inconclusive candidate. The frozen Brain source/golden pack remains evaluator-only and has no runtime score.

One test run stalled before collection while the kernel waited on reads under the fuseblk workspace; diagnostics observed pytest configuration/import/temp-path reads. An explicit equivalent pytest.ini, explicit plugins and fresh owned temporary directory permitted the recorded run. This is an environment-specific workaround, not proof of a universal cause; no global pytest settings were changed.

## Runtime and schema

Project lock installs Python3.12.9, Pydantic AI slim2.54.0 (explicit OpenAI/Google/Anthropic/Groq/Mistral/DBOS extras), DBOS3.2.0, Pydantic2.13.4, Litestar2.24.0, SQLAlchemy2.0.51 and AdvancedAlchemy0.34.0. Actual metadata was checked after sync; a successful resolver command alone was not counted as installation.

The independent `alembic_company.ini` / `company_alembic` lineage has its own company_alembic_version. Normal clean company001→005 install, repeat, all16-table ORM comparison and downgrade passed1 case, preserving unrelated legacy data and version markers. New DDL does not rewrite merged legacy001–016. A real clean legacy upgrade still fails in003 due to VARCHAR/UUID foreign-key mismatch; source review also found006 policy-column mismatches. This is mitigated for fresh company installs, not repaired for legacy migration.

DBOS's public `migrate` provisions its separate system schema in the same database, including application-role permissions. Queue SQL execution is tested with the actual pinned DBOS function, not a mock schema/function. Workflow registration/launch and execution are separate from migration.

## Completed package checks

| Package | Observed check | Limit |
| --- | --- | --- |
| Model registry/pricing |72 unit cases,97.63% module coverage | Synthetic cards; no live enabled model or invented current price |
| Fake worker/checkpoints |44 cases,95.41% module coverage | Synthetic replay; not DBOS/process recovery |
| JWT/access |65 initial cases; auth38 and access31 after added negatives | Strict signed identity plus current directory; no personal fallback |
| Directory |19 unit +11 PostgreSQL,96.89% module coverage | Trusted owner bootstrap; no anonymous work/owner creation |
| Registered authorization +owner controls |42 PostgreSQL cases, controls100% coverage | Current membership/work/ancestry checked under company mutex |
| Standing authority |55 unit +11 PostgreSQL,89% combined coverage | Only two reviewed fake internal tool versions; real plan records are M3 |
| Standing consumption/source link |5 PostgreSQL cases | Individual exact holds, one use, immutable source, rejection/revocation denied |
| Atomic queue and effect day |12 PostgreSQL cases | Exact and standing consume/hold/source/dispatch/enqueue share a transaction; no workflow/effect execution claim |
| Isolated company API |5 unit +15 real HTTP/PostgreSQL,96.72% coverage | Read/pause/decision only; decision_saved reports scheduled/executed false |
| Legacy SDK migration |82 targeted cases on each SDK1/SDK2;59 QA/usage regression | Live provider payload/billing conformance remains separate |
| Legacy regression |61 producer/behavior/chaos cases | Failed/cancelled Kafka startup cleanup; mocked business dependencies |
| Legacy RLS context |11 real PostgreSQL cases | Same-connection commit/rollback reset, bound values and error propagation; not every legacy policy |
| SDK/DBOS spike |One combined scenario,15 assertions, actual process kill/restart and version isolation | Registered TestModel/tools, checkpoint reuse and transactional enqueue; no paid request or governed company completion |

Counts overlap; they must not be added into a fictional full-suite total. Whole-tree checks during the next worker/provider TDD packages encountered expected missing interfaces/modules and are not counted as pass. The earlier pre-final-wave full unit run542 passes. Final integrated regression is pending until those packages are stable.

## Independent review and closure

An independent worker reproduced three integration gaps on its own database, without launching a worker/effect:

- A changed segment ID scheduled a second DBOS workflow for one action with no registered execution row. Root now requires the immutable current run/workspace/version, next persistent segment and permanent action→segment dispatch. Negative run/segment tests failed before the fix; queue/day acceptance now passes12 cases.
- A previous-day $0.40 hold could pass an authority recheck when the new day already held$5. Root's effect-boundary helper atomically transfers only unissued held cost to the actual Bangkok billing day, checking the new cap first. Exhaustion leaves the old reservation intact; unknown/issued billing is not refunded or reissued. This helper is now called by EffectStore.begin; complete effect-time recovery proof is still being extended.
- The current owner could not audit inactive work through the new resolver. Owner READ now permits existing correctly scoped inactive records; mutation/effect access remains denied. New owner/actor negatives failed before the fix; access31 passes afterward.

The review excluded unfinished API, integrated worker, provider and deployment packages. The API author later verified its own actual HTTP denial/decoder cases. New milestone integration still requires process-kill/receipt/counter/recovery and provider-transport evidence.

## Reproduce safely

Use `/mnt/data/nexus-runtime-env-2026-10-13` or `uv sync --frozen --extra dev` from backend. The original-SDK environment `/mnt/data/nexus-build-env-2026-10-13` remains separate; do not resync it when reproducing SDK1 evidence. Isolated SDK spike code/logs live under `/mnt/data/nexus-implementation-evidence-2026-10-13/dbos-spike/`.

PostgreSQL17 currently runs only for this acceptance work at a private Unix socket `/tmp/nexus-release-tests-2026-10-13/socket`, port55438. Recheck existence/live state after any continuation; temporary paths may expire. No existing server or Pi service was restarted. Each concurrent suite has its own `nexus_company_test_*` database. Fixtures refuse unspecified/wrong named databases, grant a NOSUPERUSER application role and run normal upgrade/downgrade. Never execute a destructive acceptance fixture against a populated or production database.

The CI matrix uses isolated PostgreSQL16 services and the reviewed lock; its YAML has been parsed but no remote CI run is claimed. Match each fixture's exact database name; owner-control tests reuse the governance fixture/database in their isolated job. Enqueue/day tests share their one named test database and run sequentially.

Meaningful checks: `ruff check nexus/ company_alembic/`, `ruff format --check nexus/ company_alembic/`, repository strict `mypy nexus/ --ignore-missing-imports`, complete unit regression and each real PostgreSQL matrix group. The final integrated worker tests also launch/kill only their bounded test process; no shared worker or production DBOS system is involved.

## Known technique traps

- Preserve explicit OpenAI API family while changing SDK aliases; migrate actual RunUsage property/input-output fields and deny unavailable billing. SDK-default zero is not proof that vendor usage existed.
- Pinned DBOS registers agents/steps before launch and its async queue after launch. Native agent history may use trusted pickle; public contracts are portable JSON. An interrupted I/O step may repeat; application effect intent/idempotency/reconciliation remains necessary.
- DBOS SQL enqueue updates an existing workflow timestamp while retaining its old inputs. Application code must check exact permanent input/version/app/queue binding and reject changed identities; queue deduplication does not confer action authority.
- Alembic autogeneration across metadata emitted a referencing table before adding the existing grant's scoped unique key, and reversed the unsafe order on downgrade. Review/reorder constraints and prove actual fresh replay. Never replace failure with create_all/stamp.
- Asyncpg prepared execution rejects multiple top-level DDL statements in one op.execute; use one function/trigger command per call. SQL function bodies can contain their internal semicolons.
- Litestar2.24's default Pydantic decoder passes strict=False. StrictBool alone did not reject JSON string booleans at the HTTP boundary; explicit before-validators now require literal bool values. Unit contract parsing alone did not expose this behavior.
- Litestar's AsyncTestClient portal owns another event loop. Reusing a setup-loop asyncpg pool failed; the API test uses NullPool to obtain connections on the actual requesting loop. This is an observed test-boundary choice, not a blanket production pooling ban.

## Remaining release gates

Governed registered DBOS worker/recovery, persistent model-per-request gateway and offline provider conformance, actual source/context Brain acceptance, bounded management, ARM64 sandbox build, complete StockFlow goal-to-receipt cycle, browser/dashboard/email, private access and independent restore/rollback are still required. Live vendor/owner-email acceptance requires configured scoped activation. Owner promotion to Delegated/Board remains explicit after reviewed operation; automated Meta Harness improvement remains deferred.
