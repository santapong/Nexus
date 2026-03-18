# NEXUS + KeepSave Integration Guide

This guide covers how NEXUS integrates with [KeepSave](https://github.com/santapong/KeepSave) for secure secret management, OAuth 2.0 authentication, and MCP gateway access.

## Table of Contents

1. [Overview](#overview)
2. [Why KeepSave?](#why-keepsave)
3. [Architecture](#architecture)
4. [Setup & Configuration](#setup--configuration)
5. [Secret Management](#secret-management)
6. [OAuth 2.0 Integration](#oauth-20-integration)
7. [MCP Gateway Integration](#mcp-gateway-integration)
8. [Environment Promotion Pipeline](#environment-promotion-pipeline)
9. [A2A Protocol Security](#a2a-protocol-security)
10. [Multi-Tenant Deployment](#multi-tenant-deployment)
11. [Deployment](#deployment)
12. [Troubleshooting](#troubleshooting)

---

## Overview

**KeepSave** is a secure environment variable storage and management platform that provides:
- AES-256-GCM encrypted secret vault with envelope encryption
- OAuth 2.0 identity provider (authorization code, client credentials, PKCE)
- Central MCP Server Hub with automatic secret injection
- Environment promotion pipeline (Alpha → UAT → PROD)
- Scoped API keys for agent runtime access

NEXUS uses KeepSave to eliminate hardcoded secrets, centralize credential management, and secure the A2A gateway — addressing critical findings from the security audit.

---

## Why KeepSave?

### Security Audit Findings Resolved

| Finding | Severity | Resolution via KeepSave |
|---------|----------|------------------------|
| Hardcoded JWT secret in `settings.py` | Critical | JWT secret stored in KeepSave vault, fetched at startup |
| Hardcoded A2A dev token in `gateway/auth.py` | Critical | A2A tokens stored as encrypted secrets with rotation |
| Secrets in `.env` files | High | Only `KEEPSAVE_URL` + `KEEPSAVE_API_KEY` in `.env` |
| No secret rotation | Medium | KeepSave promotion pipeline handles rotation per-environment |

### Before vs After

**Before (insecure):**
```bash
# .env — all secrets in plaintext on disk
ANTHROPIC_API_KEY=sk-ant-api03-...
GOOGLE_API_KEY=AIza...
DATABASE_URL=postgresql+asyncpg://nexus:password@localhost:5432/nexus
JWT_SECRET_KEY=nexus-dev-secret-change-in-production  # hardcoded!
```

**After (KeepSave):**
```bash
# .env — only 3 non-sensitive bootstrap values
KEEPSAVE_URL=http://localhost:8080
KEEPSAVE_API_KEY=ks_...
KEEPSAVE_PROJECT_ID=<uuid>
NEXUS_ENV=alpha
```

All sensitive secrets are encrypted at rest in KeepSave's vault (AES-256-GCM) and fetched at runtime.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  NEXUS Backend (Litestar)                                       │
│                                                                 │
│  ┌──────────────┐     ┌──────────────┐     ┌────────────────┐  │
│  │  settings.py  │────►│  ModelFactory │────►│  Agent Runtime │  │
│  │  (loads from  │     │  (uses keys  │     │  (CEO,Engineer │  │
│  │   KeepSave)   │     │   from env)  │     │   Analyst,etc) │  │
│  └──────┬───────┘     └──────────────┘     └────────────────┘  │
│         │                                                       │
│         │  Startup: fetch all secrets                           │
│         │                                                       │
└─────────┼───────────────────────────────────────────────────────┘
          │
          │  KeepSave Python SDK
          │  GET /api/v1/projects/{id}/secrets?environment=alpha
          │
┌─────────▼───────────────────────────────────────────────────────┐
│  KeepSave (Go + Gin)                                            │
│                                                                 │
│  ┌──────────────┐     ┌──────────────┐     ┌────────────────┐  │
│  │  API Layer    │────►│  Crypto Layer│────►│  PostgreSQL    │  │
│  │  (validates   │     │  (AES-256-GCM│     │  (encrypted    │  │
│  │   API key)    │     │   decrypt)   │     │   at rest)     │  │
│  └──────────────┘     └──────────────┘     └────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. NEXUS starts → `settings.py` reads `KEEPSAVE_URL` and `KEEPSAVE_API_KEY` from env
2. KeepSave Python SDK fetches all secrets for the project/environment
3. Secrets are injected into `os.environ` before Pydantic Settings loads
4. `Settings` class reads values normally — no code changes needed in agents
5. Agents use `settings.anthropic_api_key`, `settings.database_url`, etc. as before

---

## Setup & Configuration

### Prerequisites

- KeepSave running at `http://localhost:8080` (see [KeepSave README](https://github.com/santapong/KeepSave))
- KeepSave Python SDK installed: `pip install keepsave`

### Step 1: Create a Project in KeepSave

```bash
# Login to KeepSave
TOKEN=$(curl -s -X POST http://localhost:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@nexus.dev", "password": "SecurePass123!"}' | jq -r '.token')

# Create NEXUS project
PROJECT_ID=$(curl -s -X POST http://localhost:8080/api/v1/projects \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "nexus", "description": "Agentic AI Company-as-a-Service"}' | jq -r '.id')
```

### Step 2: Add NEXUS Secrets

```bash
# Add all NEXUS secrets to KeepSave
for secret in \
  "ANTHROPIC_API_KEY:sk-ant-..." \
  "GOOGLE_API_KEY:AIza..." \
  "DATABASE_URL:postgresql+asyncpg://nexus:nexus_dev@localhost:5432/nexus" \
  "REDIS_URL:redis://localhost:6379" \
  "KAFKA_BOOTSTRAP_SERVERS:localhost:9092" \
  "JWT_SECRET_KEY:$(openssl rand -base64 32)" \
  "DAILY_SPEND_LIMIT_USD:5.00" \
  "DEFAULT_TOKEN_BUDGET_PER_TASK:50000"
do
  KEY="${secret%%:*}"
  VALUE="${secret#*:}"
  curl -s -X POST "http://localhost:8080/api/v1/projects/$PROJECT_ID/secrets" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"key\": \"$KEY\", \"value\": \"$VALUE\", \"environment\": \"alpha\"}"
done
```

### Step 3: Create an API Key

```bash
# Create a read-only API key for NEXUS runtime
API_KEY=$(curl -s -X POST http://localhost:8080/api/v1/api-keys \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"nexus-runtime-alpha\",
    \"project_id\": \"$PROJECT_ID\",
    \"scopes\": [\"read\"],
    \"environment\": \"alpha\"
  }" | jq -r '.key')
```

### Step 4: Configure NEXUS

Update your NEXUS `.env` file:

```bash
# .env — only bootstrap values (not sensitive)
KEEPSAVE_URL=http://localhost:8080
KEEPSAVE_API_KEY=ks_...          # from Step 3
KEEPSAVE_PROJECT_ID=<uuid>       # from Step 1
NEXUS_ENV=alpha
```

### Step 5: Update settings.py

Add KeepSave bootstrap to the top of `nexus/settings.py`:

```python
"""NEXUS settings — loads secrets from KeepSave at startup."""
from __future__ import annotations

import os
from pydantic_settings import BaseSettings

# --- KeepSave Bootstrap ---
# Fetch encrypted secrets before Pydantic Settings initializes
_keepsave_url = os.environ.get("KEEPSAVE_URL")
_keepsave_key = os.environ.get("KEEPSAVE_API_KEY")
_keepsave_project = os.environ.get("KEEPSAVE_PROJECT_ID")

if _keepsave_url and _keepsave_key and _keepsave_project:
    from keepsave import KeepSaveClient

    _client = KeepSaveClient(base_url=_keepsave_url, api_key=_keepsave_key)
    _env = os.environ.get("NEXUS_ENV", "alpha")

    for _secret in _client.list_secrets(_keepsave_project, _env):
        os.environ.setdefault(_secret["key"], _secret["value"])

# --- Standard Settings ---
class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://nexus:nexus_dev@localhost:5432/nexus"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"

    # LLM API Keys — now fetched from KeepSave, no defaults needed
    anthropic_api_key: str = ""
    google_api_key: str = ""
    openai_api_key: str = ""
    groq_api_key: str = ""
    mistral_api_key: str = ""

    # Auth — no more hardcoded secret!
    jwt_secret_key: str = ""  # MUST come from KeepSave in production
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440

    # Cost Controls
    daily_spend_limit_usd: str = "5.00"
    default_token_budget_per_task: int = 50000

    # ... rest of settings unchanged
```

---

## Secret Management

### Secrets NEXUS Stores in KeepSave

| Category | Secrets | Notes |
|----------|---------|-------|
| **LLM Providers** | `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`, `MISTRAL_API_KEY` | Per-role model assignment in ModelFactory |
| **Infrastructure** | `DATABASE_URL`, `REDIS_URL`, `KAFKA_BOOTSTRAP_SERVERS` | Different values per environment |
| **Authentication** | `JWT_SECRET_KEY` | Rotated per-environment via promotion |
| **Cost Controls** | `DAILY_SPEND_LIMIT_USD`, `DEFAULT_TOKEN_BUDGET_PER_TASK` | Configurable per environment |
| **External Services** | `TEMPORAL_HOST`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY` | Phase 4+ features |
| **A2A Security** | `A2A_INBOUND_TOKEN` | Bearer tokens for external agents |

### Secret Rotation

Use KeepSave's promotion pipeline to rotate secrets:

```bash
# 1. Update the secret in alpha
curl -X PUT "http://localhost:8080/api/v1/projects/$PROJECT_ID/secrets/<secret-id>" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"value": "<new-jwt-secret>"}'

# 2. Promote to UAT (instant, audited)
curl -X POST "http://localhost:8080/api/v1/projects/$PROJECT_ID/promote" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"source_environment": "alpha", "target_environment": "uat"}'

# 3. Promote to PROD (requires approval)
curl -X POST "http://localhost:8080/api/v1/projects/$PROJECT_ID/promote" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"source_environment": "uat", "target_environment": "prod"}'

# 4. Restart NEXUS to pick up new secrets
docker compose restart nexus-backend
```

---

## OAuth 2.0 Integration

### Use Case 1: Unified Login (SSO)

Replace NEXUS's built-in JWT auth with KeepSave OAuth 2.0 for single sign-on:

```
User clicks "Login" on NEXUS dashboard
    │
    ▼ Redirect to KeepSave OAuth
    GET /api/v1/oauth/authorize?client_id=<nexus>&redirect_uri=...&scope=read+write
    │
    ▼ User authenticates with KeepSave
    │
    ▼ Redirect back to NEXUS with authorization code
    GET http://localhost:5173/auth/callback?code=<auth-code>
    │
    ▼ NEXUS exchanges code for tokens
    POST /api/v1/oauth/token
    │
    ▼ User is authenticated in both systems
```

### Use Case 2: A2A External Agent Authentication

External agents authenticate via KeepSave OAuth before calling NEXUS's A2A gateway:

```python
# External agent code
import httpx

# Step 1: Get OAuth token from KeepSave
token_response = httpx.post("http://keepsave:8080/api/v1/oauth/token", json={
    "grant_type": "client_credentials",
    "client_id": "<external-agent-client-id>",
    "client_secret": "<external-agent-client-secret>"
})
access_token = token_response.json()["access_token"]

# Step 2: Call NEXUS A2A gateway with KeepSave token
task_response = httpx.post("http://nexus:8000/a2a/tasks", json={
    "skill": "software-engineering",
    "instruction": "Write a Python function to merge two sorted lists"
}, headers={"Authorization": f"Bearer {access_token}"})
```

---

## MCP Gateway Integration

NEXUS agents can use KeepSave's MCP Gateway to access tools from other registered MCP servers (like MedQCNN) with automatic secret injection:

```python
# In nexus/tools/adapter.py — add KeepSave MCP gateway tool

async def tool_keepsave_mcp_call(
    ctx: RunContext, server_name: str, tool_name: str, arguments: dict
) -> str:
    """Call a tool on a KeepSave-hosted MCP server.
    Secrets are automatically injected by KeepSave gateway.
    Args:
        server_name: Name of the MCP server (e.g., 'medqcnn')
        tool_name: Tool to call (e.g., 'diagnose')
        arguments: Tool arguments
    Returns: Tool execution result
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.KEEPSAVE_URL}/api/v1/mcp/gateway",
            headers={"Authorization": f"Bearer {settings.KEEPSAVE_API_KEY}"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments}
            }
        )
        return response.json()["result"]
```

---

## Environment Promotion Pipeline

### NEXUS Environment Strategy

| Setting | Alpha | UAT | PROD |
|---------|-------|-----|------|
| `DAILY_SPEND_LIMIT_USD` | `5.00` | `10.00` | `50.00` |
| `DEFAULT_TOKEN_BUDGET_PER_TASK` | `50000` | `50000` | `100000` |
| `JWT_SECRET_KEY` | dev secret | rotated monthly | rotated weekly |
| `DATABASE_URL` | local PostgreSQL | staging cluster | production HA |
| `KAFKA_BOOTSTRAP_SERVERS` | local Kafka | staging cluster | production HA |
| LLM API keys | dev keys (low limits) | staging keys | production keys |

### Promotion Workflow

```
Developer updates secret in Alpha
    │
    ▼ Preview diff
    POST /projects/{id}/promote/diff
    {"source": "alpha", "target": "uat"}
    │
    ▼ Apply promotion (instant for Alpha → UAT)
    POST /projects/{id}/promote
    │
    ▼ Test in UAT environment
    │
    ▼ Promote to PROD (requires approval)
    POST /projects/{id}/promote
    │
    ▼ Approver reviews and approves
    POST /projects/{id}/promotions/{id}/approve
    │
    ▼ Restart NEXUS with NEXUS_ENV=prod
```

---

## A2A Protocol Security

### Replacing Hardcoded A2A Tokens

The NEXUS security audit identified hardcoded A2A tokens in `gateway/auth.py`. KeepSave resolves this:

```python
# BEFORE (insecure) — gateway/auth.py
VALID_TOKENS = {"nexus-dev-token-change-me"}  # hardcoded!

# AFTER (with KeepSave) — gateway/auth.py
async def validate_a2a_token(token: str) -> bool:
    """Validate A2A bearer token against KeepSave-stored tokens."""
    # Token is fetched from KeepSave at startup and cached
    valid_token = os.environ.get("A2A_INBOUND_TOKEN", "")
    return hmac.compare_digest(
        hashlib.sha256(token.encode()).hexdigest(),
        hashlib.sha256(valid_token.encode()).hexdigest()
    )
```

### A2A Token Rotation

```bash
# Generate new A2A token
NEW_TOKEN=$(openssl rand -hex 32)

# Update in KeepSave
curl -X PUT "http://localhost:8080/api/v1/projects/$PROJECT_ID/secrets/<a2a-secret-id>" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"value\": \"$NEW_TOKEN\"}"

# Distribute new token to authorized external agents
# Restart NEXUS to pick up new token
docker compose restart nexus-backend
```

---

## Multi-Tenant Deployment

For NEXUS Phase 4+ multi-tenant SaaS deployments, use KeepSave organizations:

### One KeepSave Project per NEXUS Workspace

```bash
# Create a KeepSave org for NEXUS tenants
curl -X POST http://localhost:8080/api/v1/organizations \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name": "NEXUS Tenants", "description": "Per-workspace secret isolation"}'

# Create project per tenant workspace
curl -X POST http://localhost:8080/api/v1/organizations/<org-id>/projects \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name": "nexus-workspace-acme", "description": "ACME Corp AI Company"}'
```

Each NEXUS workspace gets:
- Its own KeepSave project with isolated secrets
- Separate API keys per environment
- Independent promotion pipelines
- Tenant-scoped audit trails

---

## Deployment

### Docker Compose (Development)

```bash
# 1. Start KeepSave
cd /path/to/KeepSave
docker-compose up -d

# 2. Set up NEXUS project in KeepSave (run setup script)
./scripts/keepsave-setup.sh

# 3. Start NEXUS with KeepSave connection
cd /path/to/Nexus
export KEEPSAVE_URL=http://localhost:8080
export KEEPSAVE_API_KEY=ks_...
export KEEPSAVE_PROJECT_ID=<uuid>
docker-compose up -d
```

### Kubernetes

```bash
# KeepSave runs as a separate service
# NEXUS connects via Kubernetes service DNS:
# KEEPSAVE_URL=http://keepsave.keepsave-ns.svc.cluster.local:8080

kubectl apply -k k8s/overlays/dev
```

### Health Check

```bash
# Verify KeepSave is reachable from NEXUS
curl http://localhost:8080/healthz   # KeepSave health
curl http://localhost:8000/health    # NEXUS health

# Verify secrets are loaded
curl http://localhost:8000/health | jq '.checks'
# Should show: database: connected, redis: connected, kafka: connected
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `KEEPSAVE_API_KEY not set` | Missing env var | Add to `.env` or Docker Compose |
| `Connection refused to :8080` | KeepSave not running | Start KeepSave: `docker-compose up -d` |
| `403 Forbidden` on secret fetch | API key wrong scope | Create key with `read` scope for correct environment |
| `Empty API key values` | Wrong environment | Check `NEXUS_ENV` matches KeepSave environment name |
| Secrets not updating after rotation | Cached in memory | Restart NEXUS backend to reload secrets |

### Debug Mode

```bash
# Test KeepSave SDK connection directly
python -c "
from keepsave import KeepSaveClient
client = KeepSaveClient(base_url='http://localhost:8080', api_key='ks_...')
secrets = client.list_secrets('<project-id>', 'alpha')
for s in secrets:
    print(f'{s[\"key\"]}: {s[\"value\"][:10]}...')
"
```

### Fallback Mode

If KeepSave is unavailable, NEXUS falls back to standard environment variables:

```python
# settings.py already handles this — KeepSave bootstrap is conditional
if _keepsave_url and _keepsave_key and _keepsave_project:
    # Fetch from KeepSave
    ...
# Else: Pydantic Settings reads from env/defaults as normal
```
