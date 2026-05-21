---
name: audit-tools-mcp
description: Run a high-level audit of NEXUS tool wrappers, MCP integration, and approval guards. Use when adding new tools, integrating new MCP servers, or before a production push. Verifies that irreversible tools cannot bypass human approval. Read-only.
---

# Tool / MCP Integration Audit Skill

Audits NEXUS for tool-integration issues — especially that irreversible actions cannot fire without explicit human approval.

## When to invoke

- After adding a new tool to `backend/nexus/tools/adapter.py`
- After registering a new plugin in `backend/nexus/integrations/plugins/`
- After adding a new agent role
- Before a production deployment
- After any change to `backend/nexus/tools/guards.py`

## Workflow

Run as a single Explore subagent with the prompt template below.

### 1. Tool registry coverage

`backend/nexus/tools/registry.py` — `TOOL_REGISTRY: dict[AgentRole, list]`.

- Every tool defined in `adapter.py` is assigned to ≥ 1 role (no dead code)
- CEO has `[]` (intentional — delegates only)
- Every role has at most the tools listed in CLAUDE.md §8 — drift from spec is a finding

### 2. Approval guards on irreversible tools

For each ⚠ tool listed in CLAUDE.md §8 (`tool_file_write`, `tool_git_push`, `tool_send_email`, `tool_hire_external_agent`):

```python
async def tool_X(ctx: RunContext, ...) -> str:
    await require_approval(ctx, IrreversibleAction(...))   # MUST be first line
    return await do_the_thing(...)
```

If `require_approval()` is **absent** from the function body, the tool is unguarded. Comments like "approval is enforced by the guard chain" are not enough — there is no automatic Pydantic-AI guard chain. The call must be explicit, inside the function, before any side effect.

### 3. Plugin guards

`backend/nexus/integrations/plugins/registry.py` — `PluginTool.execute()`:

- The `requires_approval` flag on the plugin manifest must be **read and acted on**
- If `requires_approval=True` and `require_approval()` is not called → bypass bug
- HTTP-endpoint plugins: response validated against a whitelist schema before returning to agent context

### 4. Docstrings (LLM tool selection quality)

Pydantic AI uses docstrings as tool descriptions. Every `tool_*` function in `adapter.py` should have:

- One-line summary on the first line
- `Args:` block with type and meaning of each parameter
- `Returns:` block describing the shape of the output

Vague docstrings → bad LLM tool calls. Check the worst offenders first (design tools, multi-modal).

### 5. Output sanitization

Every `tool_*` function in `adapter.py` should route its output through `nexus.core.sanitization.sanitize_output()`, not just `_sanitize_tool_output()` (which is size-cap only).

```bash
grep -n '_sanitize_tool_output\|sanitize_output' backend/nexus/tools/adapter.py
```

If the count of `_sanitize_tool_output` >> `sanitize_output`, PII is leaking.

### 6. Runtime tool access enforcement

`backend/nexus/agents/base.py`. Beyond the registry-at-construction filter, there should be a runtime check that rejects any tool call outside `self.tool_access`. Without runtime enforcement, a misregistered tool or a Pydantic AI quirk can let an agent call a tool it shouldn't.

### 7. Sandbox isolation

`backend/nexus/tools/sandbox/` (E2B Firecracker, Phase 5+):

- `_check_configured()` returns False if `E2B_API_KEY` missing — but does the tool get **removed from the registry** in that case? If not, agents try to run code and get a confusing error.
- Network disabled by default in the E2B template
- Per-call timeout (30s default)
- Sandbox `.kill()` in `finally` so a hanging call doesn't burn credits

### 8. A2A outbound (`tool_hire_external_agent`)

`backend/nexus/integrations/a2a/outbound.py`:

- `require_approval()` called (this tool costs real money)
- External agent's response validated against schema before insertion into NEXUS agent's context (otherwise the external agent can prompt-inject the calling agent)
- Timeout + retry policy
- Cost cap on the response (don't accept a $50 invoice silently)

### 9. Tool timeout

Every tool should have a wall-clock timeout (`asyncio.timeout()` or HTTP client `timeout=`). Web search hanging for 60s burns task budget and may push the agent past the 5-min heartbeat timeout, causing auto-fail with no useful error.

### 10. Tool error → agent recovery

When a tool raises (e.g., `FileNotFoundError` from `tool_file_read`), the wrapper should:

- Catch the exception
- Return a string the LLM can react to (`"File not found: /foo/bar"`)
- Not let the exception propagate into the agent loop (which would mark the whole task failed)

### 11. Multi-modal tool

`tool_analyze_image`:

- Provider fallback (Claude → Gemini) on per-call basis
- 20 MB size limit enforced **before** sending to the model
- File type whitelist (PNG/JPG/WEBP/GIF/PDF)

### 12. Test asserts match registry

`backend/nexus/tests/unit/test_tools_registry*.py`. Assertion drift between test and current `TOOL_REGISTRY` is silent dead test code. Verify the test matches CLAUDE.md §8 **and** the current registry.

## Output format

```
# Tool/MCP Integration Audit — YYYY-MM-DD

## Critical (security or correctness)
- **[file:line] Title** — description + fix

## High
- ...

## Medium
- ...

## Notes
- Tools and guards that look correct
```

## Rules

- Read-only.
- For each finding, name the specific tool and the specific guard expected.
- Cap at 1500 words.
