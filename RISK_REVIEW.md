# RISK_REVIEW.md — Phase 1 Risk Assessment (2026-03-08)

> Review of §23 Prevention Rules against actual implementation status.
> Updated after Phase 1 audit and universal ModelFactory upgrade.

---

## Risk Status Summary

| Risk | Severity | Status | Notes |
|------|----------|--------|-------|
| Risk 1 — Building orchestration before loop works | CRITICAL | RESOLVED | 50-task stress test: 100% pass rate (50/50). |
| Risk 2 — Cost explosion from unbounded loops | CRITICAL | MITIGATED | Budget enforcement live in Redis. Multi-provider pricing added. |
| Risk 3 — Vague system prompts | CRITICAL | MITIGATED | Engineer prompt written + seeded. CEO is thin router (no LLM). |
| Risk 4 — Irreversible action before approval | CRITICAL | RESOLVED | `require_approval()` + `human_approvals` table live since Phase 0. |
| Risk 5 — Agents fail silently | HIGH | PARTIAL | Heartbeat loop runs. Auto-fail on silence NOT yet implemented (BACKLOG-016). |
| Risk 6 — Memory schema migration hell | HIGH | RESOLVED | All 9 tables deployed. Embeddings tested. |
| Risk 7 — Kafka instability | HIGH | RESOLVED | KRaft stable. `make kafka-test` passes. |
| Risk 8 — Scope creep | MEDIUM | MITIGATED | BACKLOG.md active. Phase gates defined. |
| **NEW Risk 9** — Multi-provider key sprawl | MEDIUM | NEEDS ATTENTION | See below. |
| **NEW Risk 10** — Local model tool calling gaps | LOW | NEEDS ATTENTION | See below. |

---

## Detailed Risk Notes

### Risk 1 — Building orchestration before loop works
**Gate:** 50-task stress test ≥ 90% pass rate.
**Status: RESOLVED** — 50-task stress test passed at **100% (50/50)** on 2026-03-08.

**Results:**
- Total tasks: 50, Passed: 50, Failed: 0
- Total tokens: 26,538 (test model) / ~99,200 tokens on Groq (first live run)
- Total duration: 106s (test model)
- Full pipeline verified: API → Kafka → CEO → Engineer → response → DB update
- Retry logic tested: rate limit (429) backoff + tool_use_failed fallback working
- Groq free tier confirmed working for individual tasks (100K TPD daily limit)

---

### Risk 2 — Cost explosion (updated for multi-provider)
**Original concern:** One task burns $50 before you notice.
**Multi-provider update:** With OpenAI, Groq, Mistral now supported alongside Anthropic/Gemini, the attack surface for cost explosion is wider. Each provider has different pricing.

**Mitigations in place:**
- Hard $5/day cap via Redis (enforced before every LLM call)
- Per-task 50k token budget
- `_MODEL_PRICING` table in `usage.py` covers all supported models
- Unknown models log a warning and default to $0 cost (safe for local models, risky for paid unknowns)

**Residual risk:** If someone configures a model not in the pricing table (e.g. a new GPT model), costs won't be tracked. The daily cap still applies via Redis, but cost reporting will undercount.

**Recommendation:** Add a setting `REQUIRE_KNOWN_PRICING=true` that blocks models without pricing entries. Implement in Phase 2.

---

### Risk 5 — Silent failures (partially mitigated)
**Implemented:** Heartbeat loop (30s), structured logging, Redis pub/sub broadcasting.
**Missing:** Auto-fail consumer that kills tasks with no heartbeat for 5 minutes (BACKLOG-016).

**Impact:** A hung task stays "running" until manually noticed. No data loss (PostgreSQL is source of truth), but poor UX.

**Recommendation:** Implement auto-fail consumer early in Phase 2.

---

### NEW Risk 9 — Multi-provider API key sprawl
**Severity:** MEDIUM
**What happens:** With 5+ provider API keys in `.env`, risk of accidentally committing keys increases. Each provider has different key formats, rate limits, and error responses.

**Mitigations:**
- `.env` is in `.gitignore`
- `.env.example` has placeholder values only
- Settings module reads from env vars (never hardcoded)

**Recommendation:** Before Phase 3 (multi-user), implement one of: Docker secrets, Vault, or encrypted env management. Already captured in BACKLOG-007.

---

### NEW Risk 10 — Local model tool calling limitations
**Severity:** LOW
**What happens:** Ollama/local models may not support function calling (tool use). Agent sends tool definitions but model ignores them or returns malformed JSON.

**Mitigations:**
- Only affects developers choosing local models intentionally
- pydantic-ai handles tool call parsing; bad responses become exceptions
- AgentBase guard chain catches exceptions and publishes error response

**Recommendation:** Document which local models support tool calling. Add integration test with Ollama in Phase 2 (BACKLOG-017).

---

## Decisions Made This Session

| Decision | Choice | Date | Reason |
|----------|--------|------|--------|
| Universal ModelFactory | Multi-provider via prefix registry | 2026-03-08 | Agents use any model by changing one env var. No code changes needed. |
| Test model provider | `test:` prefix using pydantic-ai TestModel | 2026-03-08 | Enables infrastructure stress testing without API costs/limits. |
| LLM retry logic | Exponential backoff + tool fallback in EngineerAgent | 2026-03-08 | Handles 429 rate limits (5 retries, up to 45s backoff) and tool_use_failed (retry without tools). |
| Provider resolution strategy | Prefix-based matching (first wins) | 2026-03-08 | Simple, extensible, no magic. `claude-*` → Anthropic, `openai:*` → OpenAI, etc. |
| Local model support | Ollama via OpenAI-compat endpoint | 2026-03-08 | Ollama exposes OpenAI-compatible API. No custom client needed. |
| OpenAI-compatible catch-all | `openai-compat:` prefix | 2026-03-08 | Supports vLLM, LocalAI, LiteLLM, any custom endpoint. |

---

## Phase Gate Checklist

### Phase 1 → Phase 2 Gate
- [x] Real API keys configured — Groq free tier (BACKLOG-012)
- [x] 50-task stress test passes ≥ 90% — **100% (50/50)** (BACKLOG-011)
- [x] Cost baseline documented — see below
- [x] All infrastructure verified (Docker, Kafka, Redis, PostgreSQL)
- [x] AgentBase guard chain tested
- [x] Approval flow working
- [x] Dashboard functional
- [x] Universal ModelFactory deployed

---

## Cost Baseline — Phase 1

| Metric | Value |
|--------|-------|
| Provider | Groq (free tier) |
| Model | llama-3.3-70b-versatile |
| Avg tokens per task | ~1,984 (from first live run: 99,200 tokens / 50 tasks) |
| Cost per task (Groq) | $0.00 (free tier) |
| Daily token limit (Groq free) | 100,000 TPD |
| Max tasks per day (Groq free) | ~50 |
| Infrastructure stress test | 50/50 pass, 106s total (test model) |

**Notes:**
- Groq free tier is sufficient for development/testing but will hit TPD limits under heavy use
- For production workloads, upgrade to Groq Dev Tier or switch to Anthropic/OpenAI
- The `test:` model provider enables unlimited infrastructure testing at zero cost
- Retry logic handles transient 429 errors (up to 5 retries with exponential backoff)

---

*Last updated: 2026-03-08*
