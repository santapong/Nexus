# KeepSave Tool Calling Architecture

How NEXUS agents interact with KeepSave for secret management, API key rotation,
and MCP gateway access — with dual approval for security-sensitive operations.

## Overview

NEXUS agents can now call KeepSave directly through the tool calling layer.
This enables agents to manage secrets, rotate API keys, promote environments,
and invoke external MCP tools — all with proper security controls.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  NEXUS Agent (CEO, Engineer, etc.)                                  │
│                                                                     │
│  "I need to rotate the Anthropic API key"                          │
│         │                                                           │
│         ▼                                                           │
│  ┌──────────────────────────────────────┐                          │
│  │  1. Nexus Approval Gate (guards.py)  │ ◄── Human approves in   │
│  │     IRREVERSIBLE_TOOLS check         │     Nexus dashboard      │
│  │     Polls HumanApproval table        │                          │
│  └──────────────┬───────────────────────┘                          │
│                 │ Approved                                          │
│                 ▼                                                   │
│  ┌──────────────────────────────────────┐                          │
│  │  2. KeepSave Tool Function           │                          │
│  │     tool_keepsave_update_secret()    │                          │
│  │     (nexus/keepsave/tools.py)        │                          │
│  └──────────────┬───────────────────────┘                          │
└─────────────────┼───────────────────────────────────────────────────┘
                  │ HTTPS (async httpx)
┌─────────────────▼───────────────────────────────────────────────────┐
│  KeepSave API                                                       │
│                                                                     │
│  PUT /api/v1/projects/{id}/secrets/{secretId}                      │
│         │                                                           │
│         ▼                                                           │
│  ┌──────────────────────────────────────┐                          │
│  │  3. KeepSave Approval (for PROD)     │ ◄── Admin approves in   │
│  │     Promotion pipeline enforcement    │     KeepSave dashboard  │
│  │     Alpha→UAT: instant               │                          │
│  │     UAT→PROD: requires approval      │                          │
│  └──────────────┬───────────────────────┘                          │
│                 │                                                    │
│                 ▼                                                   │
│  ┌──────────────────────────────────────┐                          │
│  │  4. AES-256-GCM Encrypted Storage    │                          │
│  │     + Audit Trail                     │                          │
│  └──────────────────────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────┘
```

## Dual Approval Flow

Security-sensitive operations pass through TWO approval gates:

### Gate 1: Nexus Human Approval (guards.py)

When an agent calls an irreversible KeepSave tool (e.g. `tool_keepsave_update_secret`):

1. Agent requests approval → `HumanApproval` record created in Nexus DB
2. Event published to Kafka `human.input_needed`
3. Agent **blocks** (polls every 2s) until human resolves
4. Human approves/rejects via Nexus dashboard → `POST /approvals/{id}/resolve`
5. If approved → tool function executes the KeepSave API call

### Gate 2: KeepSave Promotion Approval

For environment promotions targeting PROD:

1. Nexus agent calls `tool_keepsave_promote_environment(uat, prod)`
2. KeepSave creates a `promotion_request` with status `pending`
3. KeepSave admin must approve via dashboard or API
4. Once approved, secrets are copied to PROD environment
5. Agent receives confirmation or pending status

**Result**: Even if a Nexus human approves the action, KeepSave still enforces
its own security policy for PROD changes. Defense in depth.

## Tool Registry

### Read-Only Tools (no approval needed)

| Tool | Description | Roles |
|------|-------------|-------|
| `tool_keepsave_list_secrets` | List secret names and metadata | CEO, Engineer, Analyst, QA |
| `tool_keepsave_get_secret_info` | Get metadata for a specific secret | CEO, Engineer, Analyst, QA |
| `tool_keepsave_get_secret_versions` | View version history | CEO, Engineer, Analyst, QA |
| `tool_keepsave_preview_promotion` | Dry-run a promotion | CEO, Engineer, Analyst, QA |
| `tool_keepsave_list_promotions` | View promotion history | CEO, Engineer, Analyst, QA |
| `tool_keepsave_audit_log` | View KeepSave audit trail | CEO, Engineer, Analyst, QA |
| `tool_keepsave_mcp_list_tools` | Discover MCP gateway tools | CEO, Engineer, Analyst, QA |

### Irreversible Tools (require Nexus approval)

| Tool | Description | Roles | KeepSave-side approval? |
|------|-------------|-------|------------------------|
| `tool_keepsave_update_secret` | Rotate/update a secret value | CEO, Engineer | No (direct update) |
| `tool_keepsave_create_secret` | Add a new secret | CEO, Engineer | No (direct create) |
| `tool_keepsave_promote_environment` | Promote secrets between envs | CEO, Engineer | Yes, for UAT→PROD |
| `tool_keepsave_mcp_call` | Call tool via MCP gateway | CEO, Engineer, Analyst | No (but tool may have side effects) |

## Example: API Key Rotation

**Scenario**: The Anthropic API key needs to be rotated.

```
CEO Agent: "Rotate the ANTHROPIC_API_KEY with the new key provided by the admin."

1. CEO calls tool_keepsave_get_secret_info("ANTHROPIC_API_KEY")
   → Returns: ID, current version, last updated timestamp
   [No approval needed — read-only]

2. CEO calls tool_keepsave_update_secret("ANTHROPIC_API_KEY", "sk-ant-new-key-...")
   → BLOCKED: Nexus creates HumanApproval record
   → Dashboard shows: "CEO wants to update ANTHROPIC_API_KEY"
   → Human clicks APPROVE

3. KeepSave API receives the update
   → Secret encrypted with AES-256-GCM
   → New version created (old version preserved)
   → Audit log entry written

4. CEO calls tool_keepsave_promote_environment("alpha", "uat", notes="API key rotation")
   → BLOCKED: Nexus creates HumanApproval record
   → Human clicks APPROVE
   → KeepSave promotes instantly (alpha→uat is automatic)

5. CEO calls tool_keepsave_promote_environment("uat", "prod", notes="API key rotation")
   → BLOCKED: Nexus creates HumanApproval record
   → Human clicks APPROVE
   → KeepSave creates PENDING promotion (uat→prod requires KeepSave approval)
   → KeepSave admin approves in KeepSave dashboard
   → Promotion completes

6. NEXUS backend is restarted to load new secrets from KeepSave
```

## MCP Gateway Usage

Agents can call external MCP tools hosted on KeepSave with automatic secret injection:

```
Engineer Agent: "Run diagnostics on the medical scan"

1. Engineer calls tool_keepsave_mcp_list_tools()
   → Returns: diagnose (medqcnn), model_info (medqcnn), ...
   [No approval needed — read-only]

2. Engineer calls tool_keepsave_mcp_call("diagnose", '{"image_path": "/path/to/scan.png"}')
   → BLOCKED: Nexus creates HumanApproval record
   → Human clicks APPROVE
   → KeepSave gateway auto-injects DATABASE_URL, API keys
   → MedQCNN MCP server executes diagnosis
   → Result returned to Engineer agent
```

## Configuration

Add to `.env`:
```bash
KEEPSAVE_URL=http://localhost:8080
KEEPSAVE_API_KEY=ks_...
KEEPSAVE_PROJECT_ID=<uuid>
NEXUS_ENV=alpha
```

These are the only KeepSave-related values needed in the environment.
All sensitive secrets are fetched from KeepSave's encrypted vault at runtime.
