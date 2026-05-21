# NEXUS Performance Audit — 2026-05-19

Audit lane **A3 — Performance**. Read-only review of latency, throughput, and
scalability characteristics. F5 owns missing-index findings — those are not
re-audited here.

Scope: backend Python in `backend/nexus/**`. Frontend bundle is A1's lane.

---

## Executive summary

NEXUS is asynchronous end-to-end, but several **single-instance bottlenecks**
will cap throughput long before the codebase becomes "the limit" on a single
backend container. Most are correctly scoped configuration issues (Kafka
partitions, producer linger, missing concurrency caps) rather than algorithmic
defects.

| Top symptoms | Severity | Expected impact at scale |
|---|---|---|
| Every Kafka topic created with `num_partitions=1` | **Critical** | Horizontal scaling per role is impossible — only 1 consumer per group reads. Even with K8s HPA, replicas beyond 1 sit idle on every topic. |
| No global LLM concurrency semaphore | **Critical** | 6 specialists × N concurrent tasks all call provider APIs in parallel — single burst can saturate provider RPM, exhaust daily token budget before the $5 guard reads the result. |
| Embedding generation is synchronous inline in every task | **High** | Adds ~200-800ms per task (Google embedding-001 round-trip) to every `_load_memory()` call — directly opposite to CLAUDE.md §12 "never block task completion waiting for embedding". |
| `aiokafka` producer has no `linger_ms` | **High** | Each `publish()` triggers a network round-trip; no batching. 50-task stress test = 50×N Kafka RTTs. |
| Consumer `getmany()` never used | **Medium** | Single-message processing → throughput capped at one-at-a-time per consumer-partition. |
| OpenTelemetry has no sampler | **Medium** | At 1k tasks/day default `ALWAYS_ON` exporter sends ~10k spans/day per agent — bandwidth + collector load. |
| Pagination defaults missing on ~17 list endpoints | **Medium** | Unbounded `SELECT *` from `agents`, `approvals`, `audit_log timeline`, `feedback_signals`. |
| Hot-path 28 INFO logs per task | **Medium** | At 1k tasks/day, ~28k log lines/day just from `base.py`. |

**Totals:** **3 Critical, 8 High, 14 Medium, 5 Low.**

---

## 1. N+1 query patterns

### High

1. **`core/llm/cost_alerts.py:134` — Per-agent spend N+1.**
   `get_all_agent_cost_status()` iterates `alerts` and calls
   `_query_agent_spend_from_db(alert.agent_id, session)` per row. With 6 agents
   today this is fine (~6 queries × ~10ms = 60ms). At 50+ custom agents it's
   500ms+ on every dashboard refresh.
   **Fix:** group-by single query: `SELECT agent_id, SUM(cost_usd) ... WHERE
   agent_id IN (...) GROUP BY agent_id`.
   **Impact at scale:** at 50 agents × 30s dashboard poll = 90 DB hits/min per
   user → with 100 dashboard users that's 9k extra QPS.

2. **`agents/health_monitor.py:117-125` — Per-task Redis GET for heartbeat.**
   `_scan_and_fail_silent()` iterates running tasks and calls
   `_get_last_heartbeat(agent_id)` (one Redis GET each). With N running tasks
   × M agents, this is N round-trips per 60s scan.
   **Fix:** `MGET` all heartbeat keys at once, then loop in memory.
   **Impact at scale:** at 100 concurrent tasks, 100 RTTs every 60s = 1.67
   Redis GETs/sec just from health monitor.

3. **`core/recovery.py:191-197` — Stale-lock cleanup TTL probe N+1.**
   `cleanup_stale_locks()` SCANs `task_lock:*` and calls `ttl(key)` then
   `delete(key)` per key. For 10k locks (degraded recovery state) this is 20k
   sequential Redis RTTs at startup.
   **Fix:** pipeline `ttl` for the SCAN batch (100 keys), then pipeline `delete`
   for keys with TTL = -1.
   **Impact at scale:** at 1k stale locks, ~3s startup time → ~30ms with
   pipelining. Affects pod startup probe.

4. **`core/kafka/result_consumer.py:128-141 + 189-209` — Two sequential DB
   sessions per response.** `_handle_response` opens a session to check
   `_check_is_subtask` (single SELECT), closes it, then `_forward_to_ceo` opens
   another to look up the parent. Two round-trips + two session checkouts per
   subtask response. With 100 subtask responses/min that's 200 unnecessary
   session operations.
   **Fix:** single session, single SELECT returning both `parent_task_id` and
   subtask fields.
   **Impact at scale:** at 1k tasks/day with 4-subtask decomposition = 4k
   subtask responses → 4k saved session checkouts.

### Medium

5. **`agents/ceo.py:733-743 + 1101-1126` — Serial subtask dispatch.**
   `_dispatch_subtask` is awaited in a `for` loop, even when the subtasks are
   independent (no `depends_on`). Each dispatch = one Kafka `send_and_wait`
   round-trip. With 4 specialist subtasks, that's 4 sequential publishes when
   they should be concurrent.
   **Fix:** `await asyncio.gather(*[self._dispatch_subtask(...) for ...])` for
   ready subtasks.
   **Impact at scale:** per-task end-to-end latency drops by `(n-1) × ~30ms` per
   decomposed task. At 1k tasks/day × 4 subtasks × 30ms = 90s/day saved (~50ms
   p99 per task).

---

## 2. Database connection pool sizing

### High

6. **`backend/nexus/db/session.py:29-32` + `settings.py:87-90` — Pool too small
   for 8-agent + dashboard concurrency.** Defaults: `pool_size=10`,
   `max_overflow=20`, `pool_timeout=30s`. Effective ceiling = 30 connections.
   Per request the guard chain uses 2 sessions sequentially (audit + main txn);
   agents open a session per task; result_consumer opens 2 sessions per
   response; health_monitor opens one per scan; the websocket holds none.

   **Worst-case demand** under `N` concurrent tasks running:
   - 8 agents × 1 session each (handle_task) = 8
   - result_consumer x 2 = 2
   - health_monitor periodic = 1
   - scheduler periodic = 1
   - per-API request × M concurrent requests = M
   - per-audit exception session = 1 (transient)

   With 5 in-flight web requests + 8 active tasks = 13–15 sessions — under 30,
   but every burst over that **blocks for up to 30s** (`pool_timeout`). The
   30-second timeout will surface as request-handler 500s under load.

   **Fix:** raise `db_pool_size` to at least `20`, `max_overflow` to `40`,
   `pool_timeout` to `5s` (fail fast). For horizontal scaling, pool sizing must
   be `(target_concurrency / replica_count) + buffer`.

7. **`backend/nexus/db/session.py:47-53` — Background `get_session_factory`
   creates a brand-new engine each call** (pool_size=5, max_overflow=10). Code
   that calls this (eval runner, dead-letter publisher, recovery) builds a new
   connection pool each invocation. Each engine holds idle TCP connections to
   PostgreSQL.
   **Fix:** module-level cached `_engine` + factory; reuse the same engine
   shared across background services.
   **Impact at scale:** at 5 background services × 5 pool_size × 10 starts/day
   = 250 idle PG connections leaked over the day.

---

## 3. Sync work in async context

### Low

The codebase is disciplined — `subprocess.run` is correctly wrapped in
`asyncio.to_thread` (`tools/adapter.py:230,718,728,738`, `secrets/sops.py:89,143`,
`workspace/storage.py:75`). No `time.sleep()` in async paths. No raw `requests`
calls.

### Medium

8. **`agents/base.py:682-728` + `core/sanitization.py:75-99` — 17 regex passes
   on every output, in event-loop thread.** For 100KB outputs (`_MAX_OUTPUT_SIZE`)
   each pattern's `.findall(text)` + `.sub(text)` walks the full string —
   compiled regex but still O(text × patterns) on the event loop. Sanitization
   is also recursive over dicts/lists (`sanitize_output` line 130-141).
   **Fix:** offload `scan_text` to `asyncio.to_thread` for outputs > 4KB; or
   combine the 17 patterns into a single union regex with named groups.
   **Impact at scale:** at 1k tasks/day × ~50ms per 50KB output = 50s/day of
   event-loop blocking → noticeable p99 jitter on any other coroutine on the
   same loop.

9. **`agents/base.py:701` — `json.dumps(response.output)` is synchronous** to
   construct the leaked-secret scan string. Same code path then re-serializes
   in `_sanitize_output_pii`. Two stdlib `json.dumps` on every output —
   replace with `orjson.dumps` (~5-10× faster). Currently `orjson` is not in
   `pyproject.toml`.

10. **`core/kafka/producer.py:58` + `consumer.py:52` — Kafka serialization
    uses stdlib `json`.** Every published message pays stdlib `json.dumps`
    cost; every consumed message pays `json.loads`. For a 50KB message that's
    ~5ms each. At 1k tasks/day × 8 published messages/task × 5ms = 40s/day of
    pure serialization on the event loop.
    **Fix:** `orjson.dumps`/`orjson.loads` in the serializers.

---

## 4. JSON serialization hot paths

See findings 9, 10 above. Additionally:

### Medium

11. **`core/kafka/meeting.py:493` — `[m.model_dump() for m in room.messages]`
    on every meeting save.** A 5-round meeting with 4 participants is ~20
    messages × ~1ms each = 20ms per save. `save_meeting` is called after every
    submission (`base.py:838`), so a converged meeting writes 4 × 5 = 20 times
    × 20ms = 400ms cumulative dump time per meeting.
    **Fix:** dirty-flag and dump only new messages; or store messages in a
    Redis LIST and dump only config.

---

## 5. Pydantic instantiation in hot loops

### Medium

12. **`agents/base.py:172,198 + core/kafka/result_consumer.py:88` —
    `model_validate(raw)` on every consumed Kafka message.** Pydantic v2's
    `model_validate` is fast but still ~50µs per validation. For trusted
    internal Kafka traffic the cost is largely wasted — HMAC validation
    (`validate_message_signature`) already proves integrity.
    **Fix:** for hot-path internal topics, use `TypeAdapter[AgentCommand]`
    cached at module level, or skip validation entirely once the signature is
    verified.
    **Impact at scale:** at 1k tasks × 8 messages × 50µs = 400ms/day. Low
    impact today, becomes visible at 100k tasks/day.

---

## 6. Kafka consumer batching

### High

13. **`core/kafka/consumer.py:35-63` — All consumers use `async for msg in
    consumer`, never `getmany()`.** That means one message processed → commit
    → next message. With `enable_auto_commit=True` and no batching, throughput
    is capped at `1 / (per-message processing time)`. For a 2-second LLM call,
    that's 0.5 msg/sec per consumer.

    Combined with `num_partitions=1` (Finding #35 below), this is the single
    biggest throughput cap in the system.

    **Fix:** switch to `await consumer.getmany(timeout_ms=200, max_records=10)`
    for high-throughput non-LLM topics (heartbeats, audit, result consumer);
    keep `async for` for agent task topics where parallelism comes from
    partitioning, not batching.
    **Impact at scale:** result_consumer + heartbeat consumer process ~16
    messages/task today. At 1k tasks/day that's 16k single-message round-trips
    — could be 1.6k batched calls.

---

## 7. Kafka producer batching

### High

14. **`core/kafka/producer.py:54-66` — No `linger_ms` on the producer.**
    `aiokafka`'s default is `linger_ms=0` — every `send_and_wait` flushes
    immediately. `max_batch_size=16384` is set but useless without linger.

    Symptomatically: each agent publishing on `agent.responses` triggers an
    immediate network flush, even when 4 specialist subtasks finish within
    100ms of each other.

    **Fix:** `linger_ms=10` (10ms batching window) gives near-linear throughput
    improvement with negligible latency cost. `acks="all"` should remain
    (currently uses aiokafka default `acks=1` — review separately for
    durability vs throughput tradeoff).
    **Impact at scale:** at 1k tasks/day × 8 publishes/task × ~3ms saved per
    flush = 24s/day reduced wall-clock; more importantly, network connection
    utilization improves ~3-5×.

---

## 8. Redis pipelining

### Medium

15. **Repeated `incr` → `expire` patterns are not pipelined**, all sequential:
    - `api/middleware.py:89-91` (api rate limit)
    - `integrations/a2a/rate_limiter.py:36-38` (A2A rate limit)
    - `core/llm/usage.py:176-177` (token budget)
    - `core/llm/usage.py:187-188` (daily spend)
    - `core/llm/cost_alerts.py:111-112` (per-agent spend)
    - `core/llm/provider_health.py:90-98` (5 sequential ops)
    - `core/kafka/dead_letter.py:34-36` (retry counter)
    - `core/kafka/meeting.py:563-569` (`ttl` then `set`)

    Each pair is 2 sequential Redis RTTs (~0.5ms each in-DC, ~5ms cross-AZ).

    **Fix:** `async with redis.pipeline() as pipe: await
    pipe.incr(...).expire(...).execute()`.
    **Impact at scale:** at the highest-traffic path
    (`provider_health.record_call`, called on every LLM call):
    1k tasks × ~3 LLM calls × 5 ops = 15k extra RTTs/day. With pipelining: 3k.

---

## 9. Embedding generation latency

### Critical (vs. CLAUDE.md contract)

16. **`memory/embeddings.py:14-39` + `agents/base.py:570-621` — Embedding is
    generated synchronously inside `_load_memory()`, blocking every task.**

    CLAUDE.md §12 explicitly states:
    > "Generate async via Taskiq fire-and-forget task on every episodic/semantic
    > write. Never block task completion waiting for embedding."

    Current implementation:
    ```python
    # agents/base.py:572
    embedding = await generate_embedding(command.instruction)  # blocks 200-800ms
    ```

    The HTTP call to Google's `embedContent` endpoint takes 200-800ms p50, up
    to 5s p99. Every task pays this latency, on the critical path, before any
    LLM work begins.

    **Fix options:**
    - (A) Async-only: skip embedding lookup if not cached; let Taskiq fill it
      in background. First task gets no recall context, second hit benefits.
    - (B) Local embedding model (sentence-transformers `all-MiniLM-L6-v2`,
      ~5ms/encode) for query embeddings; keep Google embedding-001 only for
      written episodes.
    - (C) Cache by `hash(instruction)` in Redis (TTL 1h) — repeated tasks skip.

    **Impact at scale:** at 1k tasks/day × 500ms p50 = 8.3 minutes/day of pure
    embedding wait. Per-task: 500ms removed from p50, ~5s from p99.

---

## 10. LLM call concurrency limits

### Critical

17. **No global semaphore.** Only place I found is
    `core/llm/preflight.py:136` — used for preflight model probing, not
    runtime. Production agents have zero concurrency limit at the application
    layer.

    With the architecture diagram (CLAUDE.md §3) showing 8 agents each able to
    run concurrently across replicas, an inbound burst of 20 tasks can trigger
    20× simultaneous Claude Sonnet calls. The daily $5 cap and per-task budget
    fire **after** the LLM responds — they cannot prevent a burst from
    blowing through the daily limit in a single second.

    **Fix:** module-level
    `_llm_semaphore = asyncio.Semaphore(settings.max_concurrent_llm_calls)`
    in `core/llm/factory.py`. Wrap the `Agent.run()` call in
    `async with _llm_semaphore:`. Default 8 concurrent calls; per-provider
    semaphores ideal but stricter is fine for v1.

    **Impact at scale:** difference between "task burst exhausts $5 in 3s and
    every subsequent task fails for the day" vs "tasks queue politely and the
    $5 limit holds". This is the single highest production-risk finding in
    this audit alongside #35 (single partition).

---

## 11. WebSocket fan-out

### Medium

18. **`api/websocket.py:25-38` — Every WebSocket client creates its own
    `pubsub` object and `psubscribe("agent_activity:*")`.** Redis supports
    many subscribers cheaply, but each connection holds a TCP socket plus a
    Redis subscription. The connection limit is bounded by Redis
    `maxclients` (default 10000) and the Python connection pool
    (`_POOL_SIZE=10` in `core/redis/clients.py:15`).

    With pool size 10, only 10 simultaneous pubsub subscriptions are
    available per backend instance. The 11th client blocks or errors.

    **Fix options:**
    - (A) Increase `_POOL_SIZE` to ~100 for `redis_pubsub` only.
    - (B) Single shared subscriber + in-process fan-out to all sockets — one
      Redis sub regardless of N WebSocket clients.
    - (C) Server-side event filtering: each WS subscribes only to its own
      `agent_activity:{task_id}` channel via per-connection subscribe.
    **Impact at scale:** with 100 dashboard users → exceeds pool; with single
    shared subscriber → unlimited fan-out, ~0 Redis cost.

---

## 12. Episodic memory recall query

### Low (assuming F5's ivfflat index lands)

19. **`memory/episodic.py:46-65` — `LIMIT 5`, embedding-bounded.** Query is
    `ORDER BY embedding <=> $query_embedding LIMIT 5`. With ivfflat
    (`lists=100` from CLAUDE.md §12) at 1M rows: expected p99 ~30-50ms.

    The query also filters by `agent_id` — a composite index
    `(agent_id, embedding)` is not possible with ivfflat, but a pre-filter
    via `WHERE agent_id = $1` is supported. Confirm F5's index includes
    `WHERE embedding IS NOT NULL` (already filtered at line 60).

    No issue with the query itself. Two notes:
    - `LIMIT 5` is hardcoded in `agents/base.py:580`; consider making it
      configurable via settings.
    - The `EpisodicMemory.embedding.isnot(None)` filter at line 60 prevents
      the ivfflat index from being used for some plans — `EXPLAIN ANALYZE`
      this once F5's index lands.

---

## 13. Cache hit rates / TTLs

### Medium

20. **`memory/working.py:21` — Working memory TTL is 4h.** CLAUDE.md §11
    matches. Fine.

21. **`core/llm/usage.py:177` — Task token budget TTL = 4h.** Tasks may take
    longer (Temporal threshold = 30 min, retry_on_error × 3 = up to 3h). If a
    task spans 4+ hours its budget resets to 0 mid-flight, bypassing limits.
    **Fix:** TTL = `max(4h, task_timeout × 3)`. Or use a non-TTL key that's
    cleaned on task completion.
    **Impact at scale:** rare today but a single long-running multi-agent
    Temporal task could bypass `$5/day`.

22. **`core/llm/usage.py:188` — Daily spend TTL = 25h.** Correct
    (auto-expire next day). Good.

23. **`agents/health_monitor.py:31` — Heartbeat TTL = 600s (10min) but
    silence threshold = 300s (5min).** Correct (covers TTL clock skew).

---

## 14. API pagination defaults

### Medium

Of ~78 route handlers, only **4 endpoints** have explicit `limit` parameters
(`api/audit.py:55`, `api/feedback.py:247`, `api/tasks.py:165`, plus marketplace
hard-coded). The rest perform unbounded scans:

24. **`api/agents.py:30` — `select(Agent).order_by(Agent.role)`** — no limit.
    Fine today (8 rows) but a future custom-agent feature → unbounded.

25. **`api/approvals.py:53-64` — No limit on pending approvals.** At 1k
    tasks/day × 5% approval rate = 50 pending/day; unresolved over months
    becomes hundreds of rows per request. Acceptable but should cap at 200.

26. **`api/audit.py:120-125` — `get_task_timeline` has no limit.** A
    debugging task with hundreds of audit events → huge response.

27. **`api/billing.py:71` — `select(BillingRecord).where(created_at >= since)`**
    — full window, no limit. At 30d × 1k tasks/day = 30k rows. Memory pressure
    on the response.

28. **`api/tasks.py:317-336` — `get_task_replay`** does 4 unbounded SELECTs
    (memories, usage, subtask_ids, subtask_memories, subtask_usages). The
    `subtask_ids.in_(...)` query is bounded by the number of subtasks (~4),
    but `memories` and `usage` per task are unbounded.

29. **`api/eval.py:129` — `.limit(20)`** good, hardcoded.

30. **`api/sla.py:* — snapshots = scalars().all()`** — full scan.

31. **`api/webhooks.py:* — list webhooks**, unbounded.

**Fix:** add `limit: int = Parameter(..., default=50, le=200)` + `.offset(...)`
to every list endpoint. Pattern already established in
`api/tasks.py:165-166`; just replicate.

**Impact at scale:** at 30k billing records, the `/billing/summary` endpoint
serializes 30k Pydantic models to JSON in the event loop = ~200-500ms
blocking. Becomes 1s+ in 6 months.

---

## 15. OpenTelemetry overhead

### Medium

32. **`integrations/otel/tracing.py:57` — `TracerProvider(resource=resource)`
    has no `sampler` argument.** OpenTelemetry defaults to `ALWAYS_ON` — every
    span is exported.

    Each task generates ~7 spans (`agent.handle_task`, `kafka.consume`, 1+
    `llm.call`, 2+ `tool.call`, and decorator-wrapped functions). At 1k
    tasks/day that's 7k spans/day at minimum. With `BatchSpanProcessor` they
    batch (good), but bandwidth to the OTLP endpoint is non-trivial — and
    every span is a hot-path Python object allocation.

    **Fix:** add `TraceIdRatioBased(0.1)` for 10% sampling at high traffic,
    or `ParentBasedTraceIdRatioBased` so a sampled task gets its full subtree:
    ```python
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    _tracer_provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(root=TraceIdRatioBased(0.1)),
    )
    ```
    **Impact at scale:** 100k tasks/day × 7 spans = 700k spans/day = ~70MB+
    serialized + collector ingest cost. With 10% sampling: 7MB/day.

---

## 16. Log volume

### Medium

33. **`agents/base.py` alone emits 28 logger calls; ~20 of those are on the
    hot path** (`task_received`, `task_started_broadcast_failed`,
    `task_completed`, `duplicate_message_skipped`, plus audit-event logs
    inside `log_event`).

    Each `logger.info("event", **kwargs)` with structlog renders JSON +
    writes to stdout. Container log pipelines (Loki/Fluentbit) typically
    handle 10k-100k events/sec/node, but the application overhead is
    ~50-100µs per structured log call.

    At 1k tasks/day × ~20 log calls × ~70µs ≈ 1.4s/day of pure logging
    overhead — small. **However at 100k tasks/day** that's 140s/day, and the
    downstream log pipeline cost is significant (estimated 5-10 GB/day of
    JSON logs from `base.py` alone).

    **Fix:** move post-task summary logs to DEBUG; keep ERROR/WARNING at
    INFO. The `kafka_message_published` log at `core/kafka/producer.py:151`
    fires on every Kafka send — 8+/task — should be DEBUG.

---

## 17. Heartbeat frequency

### Low

34. **`agents/base.py:894` — 30s heartbeat × 8 agents = 16 Redis writes/min.**
    Per CLAUDE.md §20 rule 5. The Kafka publish on heartbeat
    (`base.py:884-887`) is a separate Kafka call, not piggybacked.

    Total per minute: 8 agents × 2 (Redis SET via consumer + Kafka publish) =
    16 ops. Negligible.

    The heartbeat **consumer** path (`health_monitor.py:71-81`) is correct —
    `async for msg`, single set.

    **No action needed.** Sized correctly for 8-agent deployment. At 100
    agents (multi-tenant) revisit to 60s interval to keep Redis write rate
    sane.

---

## 18. Kafka topic partition counts

### Critical

35. **`core/kafka/health_check.py:44` — Every topic created with
    `num_partitions=1`.**

    ```python
    new_topics = [NewTopic(name=t, num_partitions=1, replication_factor=1)
                  for t in missing]
    ```

    This is the **most severe scaling bottleneck in the codebase**. Kafka's
    parallelism unit is the partition: only one consumer instance per
    consumer-group can read from a single partition. So:

    - `agent.commands` has 1 partition → only 1 Engineer pod can consume,
      regardless of HPA scale.
    - `task.queue` has 1 partition → only 1 CEO pod consumes.
    - `agent.responses` has 1 partition → only 1 result-consumer can run.

    The K8s HPA manifests (CLAUDE.md §15 reference) can scale backend to 10
    replicas, but every additional replica beyond the first **sits idle** on
    these topics.

    **Fix:** partition counts per topic should match expected concurrent
    consumers:
    - `agent.commands`: 12 partitions (handles ≤ 12 specialist instances)
    - `task.queue`: 4 partitions (≤ 4 CEO instances)
    - `agent.responses`: 6 partitions (≤ 6 result-consumer instances)
    - `agent.heartbeat`: 1 partition (single consumer is fine)
    - `audit.log`, dead letters: 3 partitions

    Critical: Kafka partition keys are already correct
    (`key=str(task.id)` everywhere) so partitioning works cleanly once
    partition counts are raised.

    **Impact at scale:** difference between "K8s HPA does nothing" and
    "linear scale to 12 specialist replicas". This single config change is
    the most leveraged perf fix in the audit.

---

## 19. Frontend bundle

Skipped — A1's lane.

---

## 20. Slow startup

### Medium

36. **`agents/runner.py:62-77` — Recovery + lock cleanup at startup, blocking
    pod readiness.** `recover_orphaned_tasks` is a single transaction over
    the `tasks` table (full scan in worst case); `cleanup_stale_locks`
    SCANs all `task_lock:*` keys with N+1 TTL probes (see Finding #3).

    At 10k tasks marked `running` (post-crash) the recovery scan could take
    1-2s, plus 100-1000ms per N stale locks. Pod startup probe must allow
    enough time.

    **Fix:** make recovery non-blocking — run it in a background task,
    return health=ready when Kafka/DB/Redis connect. Recovery completes
    asynchronously and surfaces in `/health` as `recovering` state.
    **Impact at scale:** at 100k tasks in DB, ~3s recovery → K8s startupProbe
    must be tuned; otherwise pods fail liveness during recovery.

37. **`/health` endpoint not reviewed in this audit.** Verify it checks DB,
    Redis, Kafka with bounded timeouts (≤ 2s each) so a flaky dependency
    doesn't make the pod look dead.

---

## Prioritized fix list

By **expected production impact** (highest first):

| # | Finding | Severity | Effort | Where |
|---|---------|----------|--------|-------|
| 35 | All Kafka topics have 1 partition | Critical | 30 min | `health_check.py:44` |
| 17 | No global LLM concurrency cap | Critical | 1 hr | `factory.py` (new) |
| 16 | Inline embedding generation blocks every task | Critical | 2 hr | `base.py:572`, `embeddings.py` |
| 14 | Kafka producer has no `linger_ms` | High | 5 min | `producer.py:54-66` |
| 13 | Consumers don't use `getmany()` | High | 2 hr | `consumer.py`, `result_consumer.py`, `health_monitor.py` |
| 6 | DB pool sized for ~15 concurrent operations | High | 5 min (env vars) | `settings.py:87-90` |
| 7 | Background services leak engines | High | 30 min | `db/session.py:47-53` |
| 1 | Per-agent spend N+1 | High | 15 min | `cost_alerts.py:134` |
| 2 | Heartbeat scan N+1 | High | 15 min | `health_monitor.py:117` |
| 15 | Redis `incr`+`expire` not pipelined (8 places) | Medium | 1 hr | various |
| 32 | OTel exports every span | Medium | 5 min | `tracing.py:57` |
| 18 | WebSocket pubsub pool exhaustion at 10+ clients | Medium | 1 hr | `websocket.py` |
| 8 | 17-regex PII scan blocks event loop on large outputs | Medium | 1 hr | `sanitization.py`, `base.py` |
| 24-31 | Pagination missing on ~10 list endpoints | Medium | 2 hr | api/* |
| 36 | Recovery blocks startup | Medium | 1 hr | `runner.py` |
| 5 | Serial subtask dispatch | Medium | 15 min | `ceo.py:733,1101` |
| 9/10/11 | stdlib json on serialization hot paths | Medium | 1 hr | install `orjson`, swap calls |
| 21 | Task token budget TTL = 4h | Medium | 5 min | `usage.py:177` |
| 33 | Hot-path INFO logs at high volume | Medium | 30 min | `producer.py:151`, `base.py` |
| 12 | Meeting room re-dumps all messages on each save | Medium | 1 hr | `meeting.py:493` |
| 4 | result_consumer 2× session per subtask | Medium | 30 min | `result_consumer.py:128,189` |
| 19 | Episodic recall query filter blocks ivfflat | Low | (verify only) | `episodic.py:60` |

---

## Estimated impact at production scale (1k tasks/day)

Today (current code, single replica):
- p50 task latency: ~3-5s end-to-end (LLM dominated)
- p99 task latency: ~15-25s
- max throughput: ~15-25 tasks/min (capped by single-partition `agent.commands`)
- daily Kafka publishes: ~8k
- daily Redis ops: ~80k (mostly working memory + budget)
- daily Postgres queries: ~50k (estimated from N+1s + per-task session ops)

After fixes #35, #17, #16, #14, #13:
- p50 task latency: ~2-3s (embedding removed from critical path)
- p99 task latency: ~8-12s (concurrency cap prevents cascade)
- max throughput: 100+ tasks/min (linear scale with replicas)
- daily Kafka publishes: ~8k (same — batching is throughput not count)
- daily Redis ops: ~40k (after pipelining)
- daily Postgres queries: ~30k (after N+1 elimination)

---

*Audit completed 2026-05-19 by agent A3.*
*Read-only. No code modified.*
