---
name: audit-security
description: Run a high-level security audit of the NEXUS codebase. Use when the user asks for a security review, penetration audit, or before a production push. Produces a markdown report grouped by Critical / High / Medium severity. Read-only — does not fix issues.
---

# Security Audit Skill

Audits NEXUS for the most common production-breaking security issues. Reusable — run any time the security posture needs verification.

## When to invoke

- Before a production deployment or `main` merge
- After any change to `auth.py`, `oauth.py`, `api_keys.py`, `middleware.py`, `guards.py`, `tools/`, `core/kafka/signing.py`, `audit/`, or alembic RLS migrations
- Quarterly health check
- After adding a new external integration (A2A, OAuth provider, marketplace, plugin)

## Workflow

Run as a single Explore subagent with the prompt template below. Do not modify code during the audit — just report.

### 1. Auth & session

Read `backend/nexus/api/auth.py`, `oauth.py`, `api_keys.py`, `middleware.py`. Check:

- Password hashing: PBKDF2/Argon2/bcrypt with ≥ 600k iterations, `hmac.compare_digest()` on compare
- JWT: secret length ≥ 32 bytes from settings (never hardcoded), `exp` enforced on decode, `aud`/`iss` validated
- OAuth: **state parameter** generated, stored in Redis with TTL, validated in callback (CSRF defense)
- OAuth tokens at rest: encrypted with Fernet/AES — column name ending in `_encrypted` is **not** proof of encryption, read the code path
- API keys: created via Litestar-injected session (RLS-enforced), not a fresh session
- Login rate limiting: per-IP + per-email sliding window

### 2. PostgreSQL Row-Level Security (RLS)

Confirm `SET LOCAL nexus.workspace_id` is **actually executed** on every workspace-scoped request:

- Find the RLS middleware in `backend/nexus/api/middleware.py`
- Find where `set_rls_context()` is called — it must run on the **same SQLAlchemy session** the route handler uses
- A middleware that only stores `workspace_id` in `scope["state"]` but never touches the DB session means **RLS policies are dormant** (no enforcement)
- Check alembic migration 006 (or wherever RLS policies are defined) — list every table with `ENABLE ROW LEVEL SECURITY`

### 3. Approval guards on irreversible tools

`backend/nexus/tools/guards.py` + `adapter.py`. For each ⚠ tool (`tool_file_write`, `tool_git_push`, `tool_send_email`, `tool_hire_external_agent`, plus any plugin tool with `requires_approval=True`):

- `await require_approval(...)` must be the **first executable line** in the tool function
- Must not be skippable via a function argument or context flag
- Plugin tools (`PluginTool.execute()` in `integrations/plugins/registry.py`) must honor `requires_approval` — check that the flag is **read and acted on**, not just stored

### 4. Prompt injection defense

- Regex layer in `api/middleware.py` — list patterns
- LLM classifier — what model? what's the fallback behaviour on classifier failure? **Fail closed (reject), not fail open**
- Delimiter enforcement — task instructions wrapped with `<user_instruction>` before reaching system prompt
- Max instruction length enforced before DB write

### 5. Secrets handling

- `backend/nexus/settings.py` — all secrets via env, never hardcoded
- `backend/nexus/integrations/secrets/sops.py` — verify SOPS → KeepSave → env fallback order, no plaintext secrets in logs
- Grep for `print(.*key.*)`, `logger.*token.*`, `logger.*secret.*` — should return nothing
- API responses never include API keys or tokens (including in error messages)

### 6. Kafka message signing

- `backend/nexus/core/kafka/signing.py` — HMAC-SHA256 with canonical JSON
- **No dev fallback signing key in production** — must fail hard if `JWT_SECRET_KEY` is empty
- Every consumer (including `result_consumer.py`, `meeting.py`, `dead_letter.py`) calls `validate_message_signature()` before processing
- Invalid signature → dead-letter, never accept-with-warning

### 7. PII sanitization

- `backend/nexus/core/sanitization.py` — list the patterns (API keys, emails, SSN, phone, credit card)
- Confirm `sanitize_output()` is called before:
  - Publishing agent output to Kafka (in `_broadcast()` and result publish)
  - Writing to `episodic_memory.full_context`
  - Storing tool outputs (`tools/adapter.py:_sanitize_tool_output` is **size-cap only**, not PII)

### 8. A2A inbound bearer tokens

- `backend/nexus/integrations/a2a/auth.py` — token hash via PBKDF2/Argon2, not bare SHA-256 (timing/precompute attacks)
- `hmac.compare_digest()` on the comparison
- In-memory token cache: timing-safe, TTL ≤ 60 seconds
- Per-token rate limit enforced **per request**, not from stale cache

### 9. Audit log immutability

- `backend/nexus/audit/service.py` — only `INSERT` paths exist
- Grep for `UPDATE audit_log` or `DELETE FROM audit_log` — should return nothing except a legitimate archival job
- DB-level CHECK or trigger prevents backdating `created_at`

### 10. SQL injection

```bash
grep -rn 'f".*SELECT\|".*INSERT.*{\|".*UPDATE.*{\|format(.*SELECT' backend/nexus/ --include='*.py'
```

Should return zero results. All queries via SQLAlchemy parameter binding.

## Output format

```
# Security Audit — YYYY-MM-DD

## Critical (must fix before production)
- **[file:line] Title** — description + recommended fix

## High
- ...

## Medium
- ...

## Notes / things that look correct
- ...
```

## Rules

- **Read-only.** Do not modify any code.
- Cite file paths and line numbers for every finding.
- If a claim cannot be verified by reading the code, mark "needs deeper review" — do not guess.
- Cap the report at 1500 words.
