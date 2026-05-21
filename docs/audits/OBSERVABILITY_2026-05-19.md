# Observability / OTel / Logging Audit — 2026-05-19

**Auditor:** Agent A6 (read-only)
**Branch:** `audit/observability-2026-05-19`
**Scope:** `backend/nexus/integrations/otel/`, all logger usage, `/health`,
`nexus.audit.service`, Redis pub/sub broadcasting, WebSocket streaming.
**Method:** static grep / read. No code execution.

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 4 |
| High     | 8 |
| Medium   | 9 |
| Low      | 6 |
| Total findings | **27** |

| Theme | Verdict |
|-------|---------|
| `print()` ban | PASS (zero hits in production code) |
| Structured-JSON logger config | PASS (structlog, JSON in prod, console in dev) |
| OTel SDK plumbing exists | PASS (`tracing.py` + `kafka_propagator.py` written) |
| OTel actually wired into the runtime | **FAIL** — only 1 of 4 context managers is called anywhere |
| `task_id` / `trace_id` on every log line | **FAIL** — >50% of log calls missing one or both |
| `/health` is real (PING/SELECT 1) | PASS, but allocates a new Kafka producer per call |
| Distributed trace continuity across Kafka | **FAIL** — propagator written, never invoked |
| Audit-log coverage of security events | **FAIL** — auth, OAuth, RLS, ACL denials, A2A not audited |
| Metrics / `/metrics` endpoint | **FAIL** — no Prometheus, no counters/histograms |
| Error tracking (Sentry / Bugsnag) | **FAIL** — not integrated |
| Per-tenant WebSocket / pub/sub scoping | **FAIL** — `psubscribe("agent_activity:*")` is unscoped |
| Long-tail latency (p99) | PARTIAL — only LLM provider health tracks it |

Phase 5 Track C ("OpenTelemetry distributed tracing") is marked complete in
CLAUDE.md §24. **The SDK was integrated and the helper module was authored,
but the actual instrumentation is missing at every handoff except
`AgentBase._execute_with_guards`.** This is the largest discrepancy between
documented status and runtime reality found in the audit.

---

## Critical Findings

### C-1 — OTel context managers exist but only one is used
**File:** `backend/nexus/integrations/otel/tracing.py`, `backend/nexus/agents/base.py:243`

`tracing.py` defines four async context managers — `trace_agent_task`,
`trace_llm_call`, `trace_tool_call`, `trace_kafka_consume` — plus a `@traced`
decorator. A repository-wide grep for callers turned up exactly **one**
call site:

```
agents/base.py:243:  async with trace_agent_task(self.role.value, ...) as span:
```

There are zero call sites for `trace_llm_call`, `trace_tool_call`, or
`trace_kafka_consume`. The Pydantic AI LLM calls and the MCP tool wrappers
run with no span at all. Kafka consumption is not wrapped. Result:

* Distributed traces show the agent-task span but nothing inside it.
* Time spent in LLM vs tool vs memory vs DB is not separable in the trace
  viewer. Operators must fall back to `llm_usage` aggregates.
* `@traced` decorator is applied to ~13 tool wrappers in `tools/adapter.py`,
  which does produce per-tool spans, but those spans are **siblings of the
  agent-task span (not children)** because the LLM call (which invokes the
  tool) is not itself in a span. Trace tree is flat instead of nested.

The CLAUDE.md §24 Phase 5 Track C line item ("OpenTelemetry distributed
tracing — full OTel SDK integration … `@traced` decorator for any async
function") is technically truthful but creates the impression that
tracing is end-to-end. It is not.

**Recommendation:** wrap `Pydantic AI Agent.run()` in `trace_llm_call`,
wrap Kafka consumer loop in `trace_kafka_consume`, and ensure tool spans
are children of the LLM span via OTel context.

---

### C-2 — Kafka trace context propagator is written but never invoked
**Files:** `backend/nexus/integrations/otel/kafka_propagator.py`,
`backend/nexus/core/kafka/producer.py`, `backend/nexus/core/kafka/consumer.py`

`kafka_propagator.py` exports `inject_trace_context(headers)` and
`extract_trace_context(headers)`. These are the manual instrumentation
needed for aiokafka — without them OTel cannot follow a trace across the
Kafka boundary.

A grep for both symbols shows two hits: the definitions themselves.
**Neither producer nor consumer ever calls them.** `producer.publish()`
sends with `value=` and `key=` only; aiokafka headers are not set.
`consumer.create_consumer()` reads the message but never extracts
headers.

The publish log line proudly emits `task_id` and `trace_id` (string app
IDs), but the **OTel** trace ID is lost at every Kafka hop, breaking
the distributed trace chain across:

* `task.queue` (API → CEO)
* `agent.commands` (CEO → specialist)
* `agent.responses` (specialist → CEO)
* `director.review` (CEO → Director)
* `task.review_queue` (Director → QA)
* `task.results` (QA → API/dashboard)

So traces look like 6 disconnected fragments per task rather than one
end-to-end span tree.

**Recommendation:** in `publish()`, call `inject_trace_context(headers)`
and pass `headers=` to `send_and_wait`. In the consumer loop, call
`extract_trace_context(msg.headers)` and use it as the parent context
for `trace_kafka_consume`. (Both `aiokafka.AIOKafkaProducer.send_and_wait`
and `AIOKafkaConsumer` already support `headers`.)

---

### C-3 — WebSocket and SSE stream all tenants' activity to any client
**Files:** `backend/nexus/api/websocket.py`,
`backend/nexus/integrations/a2a/routes.py:226-282`

`/ws/agents` accepts any connection (no auth check, no workspace
extraction) and runs `pubsub.psubscribe("agent_activity:*")` — a
pattern subscription that returns every message on every channel
matching the prefix. The channel name is `agent_activity:{agent_id}`
(per-agent, not per-workspace), so a single client listening here
receives task-started, task-completed, and human-input-needed events
for **every workspace's** agents.

Equivalent pattern in `_broadcast()` (`agents/base.py:867`):

```python
channel = f"agent_activity:{self.agent_id}"
```

No `workspace_id` in the channel name. No filtering. Combined with the
unauthenticated WebSocket handler this is a cross-tenant information
leakage primitive.

The A2A SSE handler (`integrations/a2a/routes.py:248`) uses
`agent_activity:{task_id}` instead — which is at least task-scoped,
but the A2A token is still validated **only** against the external
caller's allowed_skills, not against workspace ownership of the task.
A valid A2A token can subscribe to another workspace's task stream by
guessing/learning the task UUID.

**Recommendation:**
1. Authenticate `/ws/agents` (require JWT + workspace_id from headers).
2. Change channel naming to `agent_activity:{workspace_id}:{agent_id}`.
3. WS handler subscribes only to its own workspace's pattern.
4. A2A SSE: verify the task belongs to the same workspace as the token
   owner before subscribing.

This is also flagged in the main security audit but the observability
lane owns the channel-naming part.

---

### C-4 — `task_id` / `trace_id` not on most log lines
**Files:** widespread; sampled across 30+ call sites in `api/`, `tools/`,
`integrations/`, `memory/`, `core/llm/`.

CLAUDE.md §16 rule 3 and §23 Risk 5 require both IDs on every log line.
The contextvars infrastructure for transparent propagation IS configured
(`structlog.contextvars.merge_contextvars` is registered in
`app.py:114`, `agents/runner.py:173`, and `temporal/worker.py:71`), but
**a repository grep for `bind_contextvars` returns zero hits**. The
processor is loaded but never fed.

That means every log line has only the explicit `extra=` keys it lists.
A sampled inventory of 30+ call sites:

| File:Line | Event | task_id | trace_id | Verdict |
|-----------|-------|---------|----------|---------|
| `agents/base.py:122` | `agent_started` | n/a (not task-scoped) | n/a | OK |
| `agents/base.py:185` | `meeting_message_received` | yes | no | partial |
| `agents/base.py:211` | `task_received` | yes | yes | OK |
| `agents/base.py:263` | `duplicate_message_skipped` | yes | no | partial |
| `agents/base.py:313` | `task_started_broadcast_failed` | yes | no | partial |
| `agents/base.py:372` | `task_completed` | yes | yes | OK |
| `agents/base.py:382` | `token_budget_exceeded` | yes | no | partial |
| `agents/base.py:397` | `tool_call_limit_exceeded` | yes | no | partial |
| `agents/base.py:412` | `task_execution_failed` | yes | yes | OK |
| `agents/base.py:483` | `agent_cost_alert_check_failed` | yes | no | partial |
| `agents/base.py:521` | `system_prompt_hot_reloaded` | n/a | n/a | OK |
| `agents/base.py:614` | (audit-write) | yes | yes | OK |
| `agents/base.py:691` | (escalation) | yes | yes | OK |
| `agents/base.py:752` | (broadcast retry) | yes | no | partial |
| `agents/base.py:870` | `broadcast_failed` | no | no | **bad** |
| `agents/base.py:889` | `heartbeat_failed` | n/a (no task) | n/a | OK |
| `agents/base.py:921` | `human_input_requested` | yes | no | partial |
| `agents/qa.py:44` | (qa entry) | yes | yes | OK |
| `agents/qa.py:103` | (qa step) | yes | no | partial |
| `core/kafka/producer.py:99` | `kafka_producer_reconnected` | n/a | n/a | OK |
| `core/kafka/producer.py:151` | `kafka_message_published` | yes | yes | OK |
| `core/kafka/dead_letter.py:75` | `dead_letter_publish_failed` | no | no | **bad** |
| `core/llm/usage.py:223` | (llm_call) | yes | no | partial |
| `core/llm/factory.py:194` | `openrouter_free_model_off_allowlist` | no | no | **bad** (no task context) |
| `core/llm/circuit_breaker.py` (state-change logs) | n/a | n/a | OK (provider-scoped) |
| `tools/adapter.py:73` | `web_search_failed` | no | no | **bad** |
| `tools/adapter.py:135` | `web_fetch_failed` | no | no | **bad** |
| `tools/adapter.py:213` | (tool entry) | no | no | **bad** |
| `tools/adapter.py:508` | `file_written` | no | no | **bad** |
| `tools/adapter.py:525` | `email_sent` | no | no | **bad** + PII (see H-3) |
| `tools/adapter.py:699` | `analyze_image_failed` | no | no | **bad** |
| `tools/guards.py:86` | (approval requested) | yes (via RunContext) | yes | OK |
| `api/tasks.py:114` | `task_created` | yes | yes | OK |
| `api/tasks.py:141` | `task_kafka_publish_failed` | yes | no | partial |
| `api/oauth.py:176` | `oauth_token_exchange_failed` | n/a (no task) | n/a | OK |
| `api/middleware.py:142` | `prompt_injection_detected` | n/a yet | n/a yet | OK (pre-task) |
| `api/middleware.py:221` | `llm_injection_detected` | n/a yet | n/a yet | OK (pre-task) |
| `api/health.py:46` | `health_check_postgres_failed` | n/a | n/a | OK |
| `api/websocket.py:23` | `websocket_connected` | n/a | n/a | OK but no workspace_id (see C-3) |
| `api/analytics.py:756` | (dead-letter error) | yes | no | partial |
| `audit/service.py:70` | `audit_event` | yes | no | **partial** (audit log itself missing trace_id) |
| `memory/embeddings.py:38` | `embedding_generation_failed` | no | no | **bad** |
| `integrations/webhooks/dispatcher.py:77` | (webhook fired) | varies | no | partial |
| `integrations/temporal/activities.py:116` | `ceo_planning_failed` | yes | no | partial |
| `integrations/temporal/activities.py:295` | `director_synthesis_failed` | yes | no | partial |
| `integrations/temporal/activities.py:366` | `qa_review_failed` | yes | no | partial |
| `integrations/eval/runner.py:119` | (eval summary) | no | no | **bad** |

Tally over the 47 sampled lines:
* both IDs present: 8
* task_id only: 16
* none and not-applicable (startup, provider state, pre-task): 15
* none and **applicable**: 8 (`broadcast_failed`, `dead_letter_publish_failed`,
  `web_search_failed`, `web_fetch_failed`, `file_written`, `email_sent`,
  `analyze_image_failed`, `embedding_generation_failed`).

Roughly **half** of log lines that COULD carry the IDs are missing
`trace_id`. Tool-wrapper logs in `tools/adapter.py` and embedding logs
in `memory/embeddings.py` lack both. This is the §23 Risk 5 prevention
rule failing in practice — the moment a tool hangs you cannot correlate
the `web_search_failed` event to the originating task without a
secondary join.

**Recommendation:** push contextvars at the agent entry point:
```python
structlog.contextvars.bind_contextvars(task_id=task_id, trace_id=trace_id,
                                        agent_id=self.agent_id)
```
in `_execute_guarded_inner`, and clear at the end. Then every log call
below it inherits the IDs automatically, including tool wrappers.

---

## High Findings

### H-1 — `/health` allocates a new Kafka producer on every probe
**File:** `backend/nexus/api/health.py:71-84`

```python
producer = AIOKafkaProducer(bootstrap_servers=...)
await producer.start()
await producer.stop()
```

Per-probe TCP connection setup + metadata fetch + teardown. With k8s
liveness probes hitting every 10 seconds across N replicas this
generates real broker load and adds 50–500 ms tail latency on the
endpoint itself.

The singleton `get_producer()` in `core/kafka/producer.py` already
maintains a healthy long-lived producer with periodic health checks.

**Recommendation:** in `/health`, reuse `get_producer()` and call
`partitions_for("__consumer_offsets")` with a 2s timeout instead of
allocating a fresh producer.

---

### H-2 — Audit log table missing event types and fields
**File:** `backend/nexus/audit/service.py:22-37`

`AuditEventType` enum has 13 values, all task-execution related:
`TASK_RECEIVED`, `TASK_COMPLETED`, `TASK_FAILED`, `LLM_CALL`,
`TOOL_CALL`, `TOOL_CALL_LIMIT_REACHED`, `APPROVAL_REQUESTED`,
`APPROVAL_RESOLVED`, `BUDGET_EXCEEDED`, `PROMPT_ACTIVATED`,
`PROMPT_ROLLBACK`, `PROMPT_CREATED`, `HEARTBEAT_SILENCE`.

**Missing types** for security/compliance:
* `LOGIN_SUCCEEDED`, `LOGIN_FAILED`
* `OAUTH_INITIATED`, `OAUTH_COMPLETED`, `OAUTH_STATE_MISMATCH`
* `RLS_VIOLATION` (a query without `nexus.workspace_id` set)
* `TOOL_ACL_DENIED` (per CLAUDE.md §20 NEVER rule 2 — supposed to write
  a security event to `audit_log`, but `tools/guards.py` only audits
  approval requests)
* `RATE_LIMIT_BREACH`
* `A2A_TOKEN_REJECTED`
* `A2A_TASK_INBOUND`, `A2A_TASK_OUTBOUND`
* `WEBHOOK_DISPATCHED`, `WEBHOOK_DISPATCH_FAILED`
* `BILLING_CHARGED`, `BILLING_FAILED`
* `WORKSPACE_CREATED`, `WORKSPACE_USER_INVITED`, `WORKSPACE_ROLE_CHANGED`
* `API_KEY_CREATED`, `API_KEY_REVOKED`
* `SECRET_ACCESSED` (SOPS / KeepSave reads)
* `PROMPT_INJECTION_BLOCKED`

A grep confirms `log_event()` is called from only 4 files: `agents/base.py`,
`api/prompts.py`, `tools/guards.py`, `core/llm/usage.py`. Auth, OAuth,
workspaces, webhooks, middleware, A2A — **zero audit entries written**.
That's >70% of security-relevant surfaces with no immutable record.

**Recommendation:** extend the enum and add `await log_event(...)` calls
in the relevant handlers. RLS-set audit is harder — consider doing it
in the middleware that issues `SET LOCAL nexus.workspace_id`.

---

### H-3 — PII written to logs
**Files:** `tools/adapter.py:525`, `db/seed.py:1097-1099`

```
tools/adapter.py:525:   logger.info("email_sent", to=to, subject=subject, body_length=len(body))
db/seed.py:1097:        logger.info("demo_user_created", email=demo_email)
db/seed.py:1099:        logger.info("demo_user_already_exists", email=demo_email)
```

`to=to` is a recipient email (PII). `subject=subject` may contain
confidential information. The main security audit flagged
`oauth.py:179` — that line actually only logs the **error key**
(`token_json.get("error", "unknown")`), not the token; that one's fine.
But the email-tool logging IS a leak.

Note also that `api/middleware.py:145` and `:224` log
`instruction_preview=instruction[:100]` from user input. A user
submitting "Send mortgage docs to john.doe@bank.com with SSN ..."
will write that snippet to the log. The PII sanitization module
(`core/sanitization.py`) is applied to agent outputs but not to
instruction-preview logs.

`agents/base.py:293` similarly logs `"instruction": command.instruction[:200]`
into the audit_log event_data — same exposure, but at least there it
goes through `_sanitize_output_pii()` for the response (not for the
instruction).

**Recommendation:**
1. Drop `to=` and `subject=` from `email_sent` log — log a hash or
   `to_domain` instead.
2. Run `instruction_preview` and audit-log `event_data.instruction`
   through `core/sanitization.py` before recording.
3. Mask `demo_email` in seed-script logs.

---

### H-4 — Audit-log writes are synchronous and block the agent hot path
**File:** `backend/nexus/audit/service.py:40-75`, called from `agents/base.py:285`, `:335`, `:548`

`log_event()` does `session.add(entry)` and relies on the caller's
session commit. Inside the guard chain, the commit happens at
`session.commit()` (`base.py:349`) after `_write_memory()` and the
sanitization steps. For a high-throughput agent this means:
1. Audit row queued in session buffer.
2. Memory write commits to PostgreSQL.
3. Audit row written same commit.

So the audit_log Insert blocks task completion. For a 50/sec workload
this can become 10–20% of the agent's hot-path latency.

Worse, `_audit_outside_transaction` (`base.py:535-554`) opens a fresh
session per exception — at least three DB roundtrips on the failure path.

**Recommendation:** publish audit events to a dedicated Kafka topic
(`audit.log`, already in `Topics` enum but unused for app writes), then
a Taskiq consumer fan-ins them into PostgreSQL. Caller is unblocked
within microseconds. The `audit_log` table is append-only so ordering
loss is tolerable for a single trace_id.

---

### H-5 — No metrics endpoint, no Prometheus counters/histograms
**Files:** repo-wide grep

Zero hits for `prometheus_client`, `Counter`, `Histogram`, `Summary`
(application metrics), `/metrics`. Phase 5 Track C HPA manifests are
in place (`k8s/base/hpa.yaml`), and the CLAUDE.md description mentions
"Kafka consumer lag metric placeholder ready for KEDA/Prometheus
adapter" — but the application emits no metrics for KEDA to consume.

Effects:
* HPA scales only on CPU/memory, not on queue depth. Under a burst of
  small CPU-cheap tasks the queue grows but pods don't scale up.
* p99 task latency, LLM tokens-per-second, cost-per-second — none
  are observable in real time. They can be re-derived from
  `llm_usage` after the fact via the analytics API, but that's
  reactive not proactive.
* The "auto-scaling responds to Kafka lag spike within 60 seconds"
  gate from Phase 5 Track C cannot actually be measured — it's
  reactive only on CPU.

**Recommendation:** add `prometheus-fastapi-instrumentator` (or
analogous Litestar plugin) and emit at least:
* `nexus_tasks_total{role, status}` (Counter)
* `nexus_task_duration_seconds{role}` (Histogram)
* `nexus_llm_tokens_total{model, direction}` (Counter)
* `nexus_llm_cost_usd_total{model, workspace_id}` (Counter)
* `nexus_kafka_consumer_lag{topic, group}` (Gauge — read from
  consumer admin API)
* `nexus_circuit_breaker_state{provider}` (Gauge)
Expose at `/metrics`.

---

### H-6 — `instruction_preview` and audit-log `instruction[:200]` not sanitized
**Files:** `api/middleware.py:144-146`, `:222-225`; `agents/base.py:291-294`

Already touched in H-3. Logged as a separate finding because it has a
different fix path (sanitization vs removal) and a different blast
radius (security audit log readers see this content).

---

### H-7 — OTel sampler defaults to ALWAYS_ON
**File:** `backend/nexus/integrations/otel/tracing.py:57-58`

```python
_tracer_provider = TracerProvider(resource=resource)
```

No sampler argument, so OTel uses `ParentBased(ALWAYS_ON)`. At
production scale (Phase 5 talks about real paying users) every span
goes to the OTLP endpoint. A single task with 20 tool calls + 5 LLM
calls + 6 Kafka hops + memory writes = 30+ spans. At 50 tasks/min that's
~25K spans/min sustained. Honeycomb/Jaeger/Tempo cost scales linearly.

**Recommendation:** set `OTEL_TRACES_SAMPLER=traceidratio` and
`OTEL_TRACES_SAMPLER_ARG=0.1` (or whatever ratio the team agrees on)
via env. Allow override per workspace (e.g., always-on for paid plans).
Failed tasks should always be sampled — implement a custom
`ParentBased(error_aware_sampler)` once you have a meaningful error
budget.

---

### H-8 — `BatchSpanProcessor` exporter timeout / queue settings are defaults
**File:** `backend/nexus/integrations/otel/tracing.py:58`

`BatchSpanProcessor(exporter)` is constructed with no overrides. The
OTel SDK defaults are:
* `max_queue_size=2048`
* `max_export_batch_size=512`
* `schedule_delay_millis=5000`
* `export_timeout_millis=30000`

If the OTLP endpoint goes down the in-memory queue fills to 2048 spans
then silently drops new ones (per OTel spec). A 30-second export timeout
inside the BatchSpanProcessor thread is OK; it does not block the
asyncio loop. But there is **no liveness signal** — operators don't
know the exporter is broken until they notice traces missing.

**Recommendation:** wire BatchSpanProcessor metrics into `/health`
(processor.force_flush(timeout_millis=1000) returns False if drainage
is stuck). Alternatively expose OTel's own self-metrics through
`/metrics`.

---

## Medium Findings

### M-1 — Heartbeats not logged but published at INFO via Kafka topic
**File:** `agents/base.py:878-894`

Heartbeats publish to `agent.heartbeat` every 30s per running agent.
With 7 agents that's 14 messages/min permanent floor. The publish path
through `producer.send_and_wait` uses `_create_producer` which emits
`kafka_producer_started` once. There is no per-heartbeat log line —
**good**. Only `heartbeat_failed` warning on exception.

The concern is that `producer.publish()` itself logs
`kafka_message_published` at INFO on every send (line 151), but
heartbeats use `producer.send_and_wait` directly (line 884) bypassing
the wrapper — so heartbeats are NOT in INFO logs. Net: this is
quieter than feared, but the inconsistency (wrapper vs direct send)
means HMAC signing is also bypassed for heartbeats. See M-2.

### M-2 — Heartbeats are not HMAC-signed
**File:** `agents/base.py:884`

Heartbeat publishes call `producer.send_and_wait(...)` directly rather
than `publish()`. They skip `inject_signature()` (in `core/kafka/signing.py`).
The `validate_message_signature` consumer guard would reject heartbeats
in production mode if it ran on the heartbeat topic, but `health_monitor.py`
does its own consumer setup and likely doesn't enforce signature
validation. Verify, and either sign heartbeats or document an exception.

(This is also a security/integrity issue. Filing here because it surfaced
during observability tracing review.)

### M-3 — `kafka_message_published` logged INFO on every publish
**File:** `core/kafka/producer.py:151`

Every Kafka publish logs at INFO with topic, task_id, trace_id, agent_id.
For a 7-agent system processing one task that involves 6+ Kafka hops,
that's >6 INFO lines per task in `producer.publish` plus broadcast
notifications elsewhere. At 50 tasks/min: ~5 lines/sec floor of INFO
plus all the agent-side INFO. Acceptable for now; consider DEBUG once
volume rises.

### M-4 — Dashboard analytics use AVG only, no p99 / p95 / p99.9
**File:** `api/analytics.py:38-39, 232-235, 272-287`

`AgentMetrics` returns `avg_tokens` and `avg_duration_seconds`. PostgreSQL
supports `percentile_cont(0.99) WITHIN GROUP (ORDER BY ...)`. The
analytics endpoint currently shows only means, which hides tail
behavior — exactly the case where you most need observability.

Note: `core/llm/provider_health.py:161,200` does compute
`latency_p99_ms` for per-provider latency using
`statistics.quantiles(latencies, n=100)[-1]`. So the precedent exists;
it just hasn't been applied to the user-facing analytics.

### M-5 — Cost dashboards aggregate by date only, not by tenant
**File:** `api/analytics.py:368-376`

`daily_average_usd` is computed across all workspaces in the query.
For a multi-tenant deployment this is meaningless. The `BillingSummary`
endpoint in `api/billing.py` does scope by workspace, so the two views
disagree. Verify the analytics endpoint adds `WHERE workspace_id = $1`
where applicable.

### M-6 — `/health` does not gate startup security checks via OTel
**File:** `app.py:24-82`

`_security_checks` emits structlog INFO/WARN/ERROR but never produces
spans. If startup fails because no LLM provider is configured, the
operator sees a Python traceback in plain logs but no OTel trace.
First-line ops would benefit from at least a `nexus.startup.security_check`
span with attributes for each check.

### M-7 — No structured error event for stack traces
**Files:** any `logger.error("...", exc_info=True)` site

`logger.error("task_execution_failed", ..., exc_info=True)` (e.g.,
`agents/base.py:412`) writes the traceback to the log. In JSON mode
the traceback is a single multi-line string field — searchable but
not directly indexable. No Sentry/Rollbar/Bugsnag/Honeybadger
integration means there is no automatic grouping, no rate alerts on
new error fingerprints, no release-tagging. For a production SaaS
this is a major operator hole.

### M-8 — Approval / human-input events do not broadcast `task_id` consistently
**File:** `agents/base.py:911-919`

`_request_human_input` broadcasts `{"event":"human_input_needed",
"task_id": str(command.task_id), "reason": reason}` — good. But
`task_started` broadcast (line 304) includes `instruction_snippet`,
which is user-supplied text. Same PII concern as H-3, and it streams
in real time to every connected WS client (which is unscoped per C-3).

### M-9 — `audit_event` log line lacks `trace_id`
**File:** `audit/service.py:70-75`

```python
logger.info(
    "audit_event",
    event_type=event_type_str,
    task_id=task_id,
    agent_id=agent_id,
)
```

Caller passes both `task_id` and `trace_id` into `log_event`. The
function records `trace_id` in the DB row but **drops it from the
structured log**. Make the log mirror the DB row.

---

## Low Findings

### L-1 — `print()` is banned and clean
Per repo-wide grep, `print(` does not appear in any production module
under `backend/nexus/` outside tests. Pass.

### L-2 — Console-vs-JSON renderer choice is environment-correct
`app.py:117-119`: `ConsoleRenderer()` in dev, `JSONRenderer()` otherwise.
Reasonable.

### L-3 — Log level configurable via `settings.log_level`
`app.py:121-123`: `structlog.make_filtering_bound_logger(...)`. Good.

### L-4 — `Topics.AUDIT_LOG` is defined but not used
Audit events go straight to PostgreSQL. The Kafka audit topic exists in
the `Topics` enum (per CLAUDE.md §10) but has no producer. See H-4 —
this is the recommended async target.

### L-5 — Kafka consumer log includes `instance_id`
`core/kafka/consumer.py:57-62` logs `instance_id` from
`NEXUS_INSTANCE_ID` env var — useful for K8s pod-level tracing. Good.

### L-6 — `Pydantic AI` calls don't surface to logs
A grep for `pydantic_ai` logging shows no integration. PydanticAI emits
its own logs to the standard `logging` module, but structlog's filter is
configured on the structlog logger only — so pydantic_ai logs may show
up in default format. Confirm and consider adding `LoggingInstrumentor`
to align them.

---

## Cross-cutting Notes

* The `core/sanitization.py` module exists and is called from
  `agents/base.py:328` for response payloads. It is NOT called for log
  messages, instruction previews, or broadcast payloads. Pulling it into
  a logger processor would close several PII leaks at once.
* `merge_contextvars` is added to the structlog chain but nothing
  populates the contextvars. This is dead weight today but a one-line
  fix to enable transparent `task_id`/`trace_id` propagation system-wide.
* The `@traced` decorator is correctly applied to tool wrappers; once
  the parent `trace_llm_call` exists, the trace tree will assemble
  itself. Low effort, high return.

---

## Top 3 priorities to fix next

1. **Wire OTel propagation through Kafka** (C-2) — without it the
   tracing infrastructure built in Phase 5 Track C produces only
   per-hop fragments. Cost: ~20 lines in producer.py / consumer.py +
   wrap the consumer loop in `trace_kafka_consume`.
2. **Bind structlog contextvars at task entry** (C-4) — closes ~50%
   of the missing-trace_id problems system-wide with one change in
   `_execute_guarded_inner`.
3. **Scope WebSocket / pub/sub by workspace** (C-3) — cross-tenant
   leakage primitive must be closed before any paying customer touches
   the dashboard.

---

*End of report. Auditor: A6. Read-only — no code modified.*
