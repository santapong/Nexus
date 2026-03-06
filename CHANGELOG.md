# CHANGELOG.md
## NEXUS — Project Change History

> **Every code change must have a CHANGELOG entry before it is committed.**
> This file is written by both humans and AI agents.
> Most recent entry at the top.
> Format defined in AGENTS.md §9.

---

## How to add an entry

Copy this template and fill it in. Delete sections that don't apply.

```markdown
## [YYYY-MM-DD] — {one-line summary of what changed}

### Added
- {new feature, file, or endpoint} — {why}

### Changed
- {what changed} — {why, what it was before}

### Fixed
- {bug description} — {root cause, fix}

### Removed
- {what was removed} — {why}

### Database
- Migration: `{migration_filename}` — {what it changes}

### Breaking
- {breaking change description} — {migration path}

**Authored by:** {engineer_agent | human | claude_code}
**Task ID:** {uuid or n/a}
**PR:** #{number or n/a}
```

---

## [2026-03-06] — Initial project planning complete — pre-build baseline

### Added
- `CLAUDE.md` v0.5 — master project document with full architecture, tech stack,
  agent roster, MCP integration, A2A gateway design, coding policies, and phased roadmap
- `AGENTS.md` v1.0 — AI agent coding policy with step-by-step workflow,
  file rules, Python/TypeScript/database rules, and mandatory documentation updates
- `CHANGELOG.md` — this file, project change history
- `ERRORLOG.md` — structured error and bug tracking log
- `DECISIONS.md` — architecture decision records (ADR) log
- `BACKLOG.md` — scope capture file (to be created on Day 1 of build)

### Architecture decisions recorded
- Pydantic AI selected as agent runtime (see ADR-001 in DECISIONS.md)
- MCP integration via Python package → Pydantic AI adapter (see ADR-002)
- A2A gateway as boundary service only (see ADR-003)
- Google embedding-001 for pgvector (see ADR-004)
- Shadcn/ui for frontend components (see ADR-005)

### Status at this entry
- All design complete. No code written yet.
- Next action: Phase 0 — project scaffolding

**Authored by:** human + claude
**Task ID:** n/a
**PR:** n/a

---

<!-- All future entries go above this line, newest first -->
