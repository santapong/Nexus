# CREATIVE_ROADMAP.md
## NEXUS — Post-GA Horizon (v1.1+)

> **Purpose.** Document the ambitious, novel, and slightly weird features that
> NEXUS should grow into **after** v1.0 GA (see `PROJECT_COMPLETION_PLAN.md`).
> None of this belongs in the 1.0 scope — putting it here is the discipline
> that keeps the GA train on schedule.
>
> **Format.** Each theme has a one-line thesis, 3–5 concrete bets, and a "kill
> criterion" — the signal that would tell us to stop working on it.
>
> **Promotion rule.** An item leaves this document only when it ships, is
> explicitly rejected (with a reason), or is promoted into `BACKLOG.md` with a
> proper phase assignment.

---

## 0. North star

**"An AI company you can walk into."** Post-GA work is organized around that
metaphor: make NEXUS feel less like a task queue and more like a living
organization a human can observe, talk to, and grow.

The three instrumental goals that serve the north star:

1. **Make the agents visible** (embodiment, space, voice, avatars).
2. **Make the work negotiable** (agents that push back, not just execute).
3. **Make the system a substrate** (others build *on* NEXUS, not just *with* it).

---

## 1. Theme A — Embodied NEXUS

> *Thesis.* A visual, spatial, and vocal NEXUS is stickier than a dashboard
> one. Modeling agents as characters in a space turns ops metrics into
> intuition.

### A1. 2D Virtual Office ([IDEA-002] / [IDEA-022])

- Phaser.js-rendered isometric office; one desk per active agent.
- Kafka events drive avatar animations: CEO "walks" to a specialist when
  publishing `agent.commands.{role}`; meeting-room topics gather avatars at a
  shared table.
- Click an avatar → slide-out panel shows live task, memory excerpts, tool
  activity.
- Day/night cycle tied to inference volume (busy → night shift graphics).
- **Kill criterion:** Session-time in the 2D view drops below 30% of total UI
  time 90 days after launch.

### A2. Voice NEXUS ([IDEA-004])

- Browser-side speech-to-text via Web Speech API for low latency; fallback to
  Whisper server-side for accuracy.
- Text-to-speech responses via OpenAI Realtime or ElevenLabs; one voice per
  agent role, consistent across sessions.
- "Daily standup" feature — NEXUS reads the previous 24 hours of task activity
  as a 2-minute briefing.
- **Kill criterion:** Voice opt-in stays below 10% of active users after 60 days.

### A3. Mobile companion (PWA) ([IDEA-006])

- Primary job: approve irreversible actions on the go. Push notification when
  `human_approvals` row opens; one-tap approve/deny with biometric unlock.
- Secondary job: quick task submission and agent status glance.
- **Kill criterion:** < 20% of approvals come through mobile after 90 days.

### A4. Ambient screens

- A long-running "lobby" view for a large monitor: current tasks, avatar
  activity, cost-per-hour gauge, Uptime Kuma status wall.
- Intended for the literal office wall. No input, pure display. Low-cost way
  to make NEXUS a team presence.

---

## 2. Theme B — Negotiating agents

> *Thesis.* The current pipeline is strictly hierarchical (CEO → specialists).
> Real teams push back. Letting specialists negotiate scope and cost turns
> NEXUS into a closer model of a real org and may surface better plans.

### B1. Agent negotiation protocol ([IDEA-028])

- New Kafka message types: `propose`, `counter`, `accept`, `reject`.
- Applies within the meeting-room pattern — specialists can counter CEO's scope
  before committing.
- Hard token budget per negotiation to prevent infinite dealing: default 4
  rounds, 2,000 tokens.
- QA reviews against the **negotiated** scope, not the original.
- **Kill criterion:** Negotiated tasks show ≥ 15% higher total cost with no
  measurable quality gain.

### B2. Self-reflection pass ([IDEA-011])

- Optional guard-chain step: agent critiques its own draft with a "critic"
  system prompt before QA.
- Feature-flagged per role. Writer and Engineer are the first candidates.
- Measured against QA rejection rate and rework cost.
- **Kill criterion:** Net tokens/task increase with no QA rejection-rate drop.

### B3. Hierarchical planning ([IDEA-025])

- CEO still does top-level decomposition; specialists can further decompose
  their subtask into micro-tasks (depth cap 3).
- Token budgets are partitioned across hierarchy levels to prevent a child
  subtree from starving siblings.
- **Kill criterion:** Depth-2 tasks complete slower than flat tasks of the
  same scope with no quality gain.

### B4. Error-cascade validator agent ([IDEA-018])

- Standalone Validator sits between CEO and specialists; blocks empty/invalid
  decompositions before any tokens are spent.
- Much narrower scope than the Director agent — the Director synthesizes
  outputs, the Validator filters inputs.
- **Kill criterion:** Decomposition failure rate is already below 2% on the
  canonical benchmark — ship only if it rises above that threshold.

---

## 3. Theme C — NEXUS as substrate

> *Thesis.* v1.0 makes NEXUS a product. v1.1 should make it a *platform* — a
> thing other developers build inside, not just against.

### C1. Plugin marketplace with revenue share ([IDEA-005] extended)

- Build on Phase 11's plugin system.
- Developers publish plugins to a curated registry; NEXUS reviews security
  manifests before listing.
- Free + paid tiers; Stripe handles developer payouts.
- Versioned signatures (Sigstore) enforce integrity across upgrades.

### C2. Browser agent extension ([IDEA-001] / [IDEA-021])

- Chrome extension using Google WebMCP (Canary) as the primary page interaction
  layer; CDP fallback for non-WebMCP sites.
- Two modes: passive (right-click → send to NEXUS) and active (agent fills
  forms, clicks through flows under approval).
- Integrates with Phase 11 plugin sandbox so a plugin can declare itself a
  "browser worker".
- **Kill criterion:** Extension DAU plateaus below 5% of active NEXUS users
  180 days post-launch.

### C3. Natural-language workflow compiler ([IDEA-034])

- Template-based mode ships in Phase 11. This entry is the **LLM-compiled**
  mode: "every Monday, research competitors and email me a summary" →
  compiled into a workflow DAG and scheduled.
- Two-step compile: LLM proposes DAG, then a rule-based validator checks it
  against the plugin registry and role catalog before execution.
- **Kill criterion:** < 50% of LLM-compiled workflows pass validation on first
  attempt after 500 samples.

### C4. Integration hub with first-party connectors ([IDEA-010] / [IDEA-026])

- Priority order (based on enterprise demand patterns):
  1. Slack — bot commands, notifications, approvals.
  2. GitHub — PR review, issue triage.
  3. Google Workspace — Docs/Sheets read/write, Calendar.
  4. Jira/Linear — ticket creation from outputs.
- Each connector is a plugin under the Phase 11 schema; no special-case code in
  core.

### C5. Agent Control Plane ([IDEA-031])

- Cross-instance dashboard for users running multiple NEXUS deployments
  (agencies, franchises, multi-product companies).
- Aggregates Jaeger traces, health metrics, cost trends, federation
  connectivity across instances.
- "Kubernetes dashboard for AI agents." Pull-based to avoid a privileged push
  channel.

---

## 4. Theme D — Memory and knowledge architecture

> *Thesis.* Flat vector memory is a floor, not a ceiling. Knowledge graphs
> unlock multi-hop reasoning that cosine similarity cannot express.

### D1. Knowledge-graph memory ([IDEA-027])

- Replace (or more likely *augment*) episodic + semantic memory with a graph
  store. Start with PostgreSQL AGE to avoid a new service; migrate to Neo4j
  only if query performance justifies the ops cost.
- Agents query "what do we know about Client X?" and traverse the graph
  instead of retrieving flat chunks.
- **Kill criterion:** Graph-augmented recall scores within noise of pure
  vector recall on the canonical benchmark after 1,000 tasks of graph data.

### D2. Federated learning across NEXUS instances ([IDEA-033])

- Shares *prompt deltas and aggregated feedback*, never raw task data.
- Differential privacy with a per-round ε budget; Prompt Creator agent must
  approve every federated prompt change before it deploys locally.
- Requires ≥ 5 consenting instances to aggregate before any update lands —
  below that threshold the system refuses to share.

### D3. Episodic memory compaction

- Long-running deployments accumulate millions of episodes. Add a compactor
  that summarizes aged episodes into a single rollup while retaining the
  source IDs for audit.
- Reuses the CEO's summarization capability under an admin role.

---

## 5. Theme E — Trust, safety, and commerce

> *Thesis.* v1.0 is secure enough to sell. v1.1 must be secure enough that a
> regulated customer (finance, healthcare, gov) can adopt NEXUS without
> concessions.

### E1. NIST CAISI alignment ([IDEA-029])

- Build a compliance dashboard mapping existing controls (`human_approvals`,
  audit log, RLS, injection classifier) to NIST CAISI requirements as they're
  published.
- Exportable report for procurement due-diligence questionnaires.

### E2. Agentic Commerce Protocol (AP2) full integration ([IDEA-032])

- Phase 10 ships AP2 mandate issuance/verification. v1.1 expands it into
  **delegated purchase flows** (pre-signed Intent Mandates) so NEXUS agents can
  transact within a bounded budget without live human approval.
- Crypto payments via `x402` remain out of scope unless a concrete customer
  need appears.

### E3. Red-team harness as a first-class feature

- Convert the Phase 12 external pen-test into a perpetual internal harness.
- Adversarial prompts, supply-chain tampering, tenant-isolation fuzzing — run
  nightly, gate releases on pass/fail.

### E4. Privacy-preserving evaluation

- Tenants opt in to share anonymized evaluation outcomes for benchmarking;
  NEXUS publishes a periodic "model leaderboard for agent roles" that is
  genuinely comparable across providers. The eval pipeline itself is the
  differentiator — not just the scores.

---

## 6. Wildcards (low-probability, high-surprise)

These are the deliberately weird bets. Most will die on contact. The few
that don't will define whatever v2.0 becomes.

- **Agents that sleep and dream.** A nightly "dream" phase where idle agents
  replay episodic memory, generate hypothetical tasks, and run them inside
  the sandbox. Outputs feed the fine-tuning dataset. Cost is capped at 5% of
  the day's spend.
- **Emotional tone modeling for agents.** Each agent gets a small persistent
  "mood" state that nudges prompts (e.g., an Engineer under heavy load
  produces terser but not worse output). Purely cosmetic unless it measurably
  changes outcomes.
- **Physical-world integration.** MQTT bridge so NEXUS can drive lab hardware
  (robotics arms, IoT sensors) as tools. Initial partner: an integration with
  the sibling `deviceforge` project.
- **Multi-player NEXUS (human + AI team).** Users share agent-steering
  responsibility like players sharing a starship in Artemis. Turns NEXUS into
  a cooperative game as well as a work tool.
- **Agent debate mode.** Two specialists publicly disagree on a subtask; a
  human or a third "judge" agent picks the winner. The disagreement itself
  becomes training data.
- **Economic agents.** An internal "market" where agents bid compute budget
  for the right to handle a task. The highest-expected-value agent wins. Only
  interesting once agent roles are dynamically configurable.
- **NEXUS as a game.** Let a user "hire" virtual employees, assign them tasks,
  and watch the company grow — but all tasks are real work the user wants
  done. A business-simulation interface on top of actual utility.

---

## 7. What we're explicitly **not** doing

To keep this list honest, the following have been considered and are *not*
on the post-GA roadmap:

- **Custom training of foundation models from scratch.** Fine-tuning is in
  scope; pre-training is not.
- **General-purpose browser automation framework.** Browser agents stay
  focused on NEXUS-originated tasks; we're not competing with Stagehand /
  Playwright.
- **End-user mobile chat app separate from the approvals PWA.** Duplicates
  the dashboard without a unique use case.
- **Agent-to-human payroll disbursement.** AP2 mandates handle *agent-to-agent*
  settlement. Paying humans is a different compliance regime entirely.
- **Own cloud.** NEXUS runs on the customer's cloud or on Dokploy; we do not
  offer a hosted tier before v1.5 at the earliest.

---

## 8. Prioritization heuristic for v1.1

When GA ships, revisit this file and rank themes by the following:

1. **User-visible delta:** does this measurably change what NEXUS *feels* like?
2. **Compound value:** does shipping this make the next thing cheaper?
3. **Reversibility:** how easy is it to roll back if the bet loses?
4. **Data prerequisite:** do we already have the data to make this work, or
   do we need to collect it first?

Current bias (subject to change when v1.0 post-mortem lands):

> **Theme A (embodied) → Theme C (substrate) → Theme B (negotiation) → Theme D
> (memory) → Theme E (trust) → Wildcards.**

Theme A first because it is the cheapest way to 10x user delight; Theme C
second because platform economics compound; Theme B third because it's
architecturally invasive but small-surface; Theme D and E are long-horizon
infrastructure; wildcards wait for slack time.

---

*Authored by:* claude_code
*Companion document:* `PROJECT_COMPLETION_PLAN.md`
*Ideas this document absorbs:* `IDEA-001`, `IDEA-002`, `IDEA-004`, `IDEA-005`,
`IDEA-006`, `IDEA-010`, `IDEA-011`, `IDEA-014`, `IDEA-018`, `IDEA-020`, `IDEA-021`,
`IDEA-022`, `IDEA-025`, `IDEA-027`, `IDEA-028`, `IDEA-029`, `IDEA-031`, `IDEA-032`,
`IDEA-033`, `IDEA-034`.
*Last updated:* 2026-04-21
