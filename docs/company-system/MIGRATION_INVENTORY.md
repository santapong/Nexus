# Company migration inventory

**Source checked:** 2026-10-13, baseline `6a8c8ef` plus the local foundation patch. This is a source inventory, not a production-data migration. No legacy database was queried.

## Existing boundaries

| Current source | Proposed mapping | Cutover requirement |
| --- | --- | --- |
| `workspaces` / `Workspace.owner_id` | Company identity and authenticated owner | Validate IDs and owner membership; do not infer from nullable task scope |
| `users`, `workspace_members` | Principals and role grants | Keep verified session/membership as authority; invitation metadata is not an active grant |
| `tasks`, parent IDs and trace strings | Logical work and goal/plan lineage | Validate IDs, identify incomplete tasks, preserve history and prevent dual execution |
| `agents` and role/model/tool configuration | Department charters and evaluated profiles | Explicit tool/resource policy and registered model API family |
| `human_approvals` and `/api/approvals` | Exact version/hash-bound decisions | Old decisions lack the new binding; return for review rather than silently elevate |
| Workspace files, versions, Git storage and attachments | Artifact references and evidence lineage | Hash content, preserve revisions, enforce source/derived-output access |
| Agent semantic/episodic memory | Typed claim/evidence history | Preserve source/type/dates; do not turn an old summary or plan into verified truth |
| Kafka task/results and Redis seen/recovery locks | DBOS work ownership and action ledger | Drain/reconcile; neither offsets nor seen markers establish completion |
| Existing cost/usage and float workspace limits | Dated model prices plus Decimal reservations | Import only verified usage, retain unknown billing, reconcile accounting differences |
| Prompt proposals and benchmark records | Versioned evaluation inputs | Keep owner promotion; no automatic Meta Harness activation |

Current consumers include `/api/tasks`, `/api/approvals`, `/api/uploads`, `/api/workspaces/.../projects`, WebSocket activity, agent runner, A2A gateway and scheduled legacy work. They remain legacy paths. No new `CompanyJournal` call is mounted in the application/router/agents by this slice.

## Schema chain and new slice

Baseline migrations are 001 through **016 attachments**. New additive **017 company journal** creates five dedicated tables: controls, exact action snapshots, daily totals, logical-work totals and cost holds. It adds company-scoped RLS and an immutable snapshot/decision/consumption guard. It does not edit or drop a legacy table. ORM metadata is added to Alembic's target metadata for future migration comparisons.

The standalone acceptance suite applies 017 alone to an empty disposable database, compares metadata, exercises a non-superuser application role, and downgrades the new tables after each case. This proves the new migration in isolation. Full-chain migration, real-data import, owner/membership mapping, API/RLS-context integration and production backup/rollback remain gates before new intake.

## Next integration steps

1. Nominate a real company/workspace and derive server scope from its authenticated owner/membership. Do not accept a client-supplied LedgerScope as authority.
2. Add explicit workspace/company mapping and parent/work quota ownership with additive migrations.
3. Register the DBOS workflow/model versions and transactional enqueue boundary; prove crash/replay and compatible upgrades.
4. Map legacy endpoint consumers through feature-gated adapters. Keep one engine owner for each work item.
5. Reconcile pending/unknown legacy actions and exact approvals before intake cutover.
6. Prove the full migration/restore sequence on a disposable copy before production application.
