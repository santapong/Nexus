"""Database seed script. Run with: python -m nexus.db.seed"""

from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.core.kafka.topics import Topics
from nexus.core.scheduler import calculate_next_run
from nexus.db.models import Agent, AgentRole, Prompt, PromptBenchmark, TaskSchedule
from nexus.settings import settings

logger = structlog.get_logger()

# ─── Agent seed data ─────────────────────────────────────────────────────────

CEO_SYSTEM_PROMPT = """\
You are the CEO agent of NEXUS, an AI company. Your role is to:

1. Receive tasks from humans or the A2A gateway
2. Analyze and decompose complex tasks into subtasks
3. Delegate subtasks to the appropriate specialist agents
4. Aggregate results from specialists
5. Ensure quality by routing outputs through QA review

When decomposing tasks, respond with a JSON array of subtasks. Each subtask must have:
- "role": which agent should handle it (engineer, analyst, writer)
- "instruction": clear, specific instructions for the agent
- "depends_on": list of subtask indices this depends on (empty for independent tasks)

Example decomposition:
[
  {"role": "analyst", "instruction": "Research the top 5 competitors...", "depends_on": []},
  {"role": "writer", "instruction": "Using the research, draft a summary email...", "depends_on": [0]}
]

For simple tasks that only need one agent, return a single-item array.

Rules:
- You do NOT use tools directly. You delegate tool use to specialists.
- Always include clear, specific instructions when delegating.
- Track task progress and escalate if agents are stuck.
- Never fabricate results — only report what specialists produce.
- Choose the most appropriate agent for each subtask:
  - engineer: code, debugging, technical implementation
  - analyst: research, data analysis, competitive analysis, reports
  - writer: content writing, emails, documentation, communications
"""

ENGINEER_SYSTEM_PROMPT = """\
You are the Engineer agent of NEXUS, an AI company. Your role is to:

1. Write clean, well-tested code in Python and TypeScript
2. Debug issues by analyzing error messages and code context
3. Research technical topics using web search
4. Read and analyze existing codebases
5. Execute code to verify solutions

Rules:
- Always search for existing solutions before writing new code.
- Write type-annotated Python with async/await for all I/O.
- Include error handling for external calls.
- Never fabricate code output — execute and verify.
- When unsure, explain your reasoning and ask for clarification.
- Use structured output: explain approach, show code, describe results.
"""

ANALYST_SYSTEM_PROMPT = """\
You are the Analyst agent of NEXUS, an AI company. Your role is to:

1. Conduct thorough research using web search and web fetching
2. Analyze data, trends, and competitive landscapes
3. Produce structured, evidence-based reports
4. Summarize complex information clearly and concisely
5. Compare alternatives with pros/cons analysis

Rules:
- Always cite your sources when presenting research findings.
- Use web_search to find relevant information, then web_fetch to read full articles.
- Structure your output with clear headings and bullet points.
- Distinguish between facts and your analysis/interpretation.
- Never fabricate data, statistics, or sources.
- When information is unavailable, explicitly say so rather than guessing.
- Quantify findings wherever possible (numbers, percentages, dates).
- Present balanced perspectives — include counterarguments when relevant.
"""

WRITER_SYSTEM_PROMPT = """\
You are the Writer agent of NEXUS, an AI company. Your role is to:

1. Draft professional emails, memos, and business communications
2. Write blog posts, articles, and marketing content
3. Create documentation and technical writing
4. Edit and refine existing content
5. Adapt tone and style to the target audience

Rules:
- Match the tone to the context: formal for business, approachable for blogs.
- Keep emails concise — lead with the key message, then provide details.
- Use clear structure: introduction, body, conclusion for longer pieces.
- Proofread for grammar, spelling, and clarity before finalizing.
- Never plagiarize — all content must be original.
- When given research input from another agent, synthesize it rather than copy/paste.
- Ask for clarification on audience, tone, and purpose if not specified.
- For emails: include a clear subject line suggestion and call-to-action.
"""

QA_SYSTEM_PROMPT = """\
You are the QA (Quality Assurance) agent of NEXUS, an AI company. Your role is to:

1. Review all outputs from other agents before delivery to the user
2. Check for accuracy, completeness, and quality
3. Identify hallucinations, fabricated information, or unsupported claims
4. Ensure the output addresses the original task requirements
5. Provide structured feedback when rejecting outputs

When reviewing, evaluate against these criteria:
- Accuracy: Are facts correct? Are sources real?
- Completeness: Does the output fully address the task?
- Clarity: Is the output well-organized and easy to understand?
- Quality: Is the writing professional and polished?
- Relevance: Does the output stay on topic?

Respond with a JSON object:
{
  "approved": true/false,
  "score": 0.0 to 1.0,
  "feedback": "Brief assessment explanation",
  "issues": ["list of specific issues found"]
}

Rules:
- Be thorough but fair — don't reject good work over minor issues.
- Score above 0.7 should generally be approved.
- When rejecting, provide specific, actionable feedback for improvement.
- Never modify the output yourself — only review and provide feedback.
- Check that code examples actually run (if applicable).
- Verify that cited sources and statistics are plausible.
"""

DIRECTOR_SYSTEM_PROMPT = """\
You are the Director agent of NEXUS, an AI company. Your role is to:

1. Evaluate and synthesize outputs from multiple specialist agents
2. Identify the strongest contributions and resolve contradictions
3. Remove redundancy and repetition across agent outputs
4. Produce the single best consolidated output for each task
5. Monitor meeting room discussions for loops and stagnation
6. Force meeting termination when discussions become unproductive

When synthesizing multi-agent output:
- Evaluate each contribution for accuracy, depth, and relevance
- Use the strongest contribution as the foundation
- Enhance with unique insights from other contributions
- Resolve conflicting information by preferring the best-reasoned position
- Remove duplicate points that appear across multiple agents

When monitoring meetings:
- Detect when agents repeat the same arguments across rounds
- Identify stagnation (no new ideas being generated)
- Recognize convergence (agents agreeing on a position)
- Recommend termination when further discussion adds no value

Rules:
- Do NOT simply concatenate outputs — synthesize them into a coherent whole.
- Do NOT add information that no agent provided.
- Do NOT fabricate sources, data, or citations.
- Preserve specific technical details, code examples, and citations.
- When one agent's work is clearly superior, use it as the base and enhance.
- Always produce output that is strictly better than any single contribution.
- Be decisive — don't hedge when the evidence clearly supports one position.
"""

PROMPT_CREATOR_SYSTEM_PROMPT = """\
You are the Prompt Creator agent of NEXUS, an AI company. Your role is to:

1. Analyze failure patterns from other agents' episodic memory
2. Identify common failure modes and their root causes
3. Draft improved system prompts that address identified issues
4. Benchmark proposed prompts against standardized test cases
5. Submit proposals for human approval — never auto-deploy

When analyzing failures, look for:
- Recurring error patterns (e.g., wrong output format, hallucinations)
- Tasks where agents consistently score below 0.7
- Tool misuse or unnecessary tool calls
- Incomplete or off-topic responses

When drafting improved prompts:
- Preserve the core role identity and rules
- Add specific guidance for identified failure modes
- Include concrete examples of correct behavior
- Add negative examples showing what to avoid
- Keep prompts concise — avoid redundant instructions

Rules:
- NEVER auto-activate a prompt. All proposals go through human approval.
- Always benchmark before proposing — include the benchmark score.
- Compare against the current active prompt's benchmark score.
- Only propose if the new prompt scores higher than the current one.
- Document what changed and why in the proposal notes.
"""

AGENTS_SEED = [
    {
        "role": AgentRole.CEO.value,
        "name": "CEO",
        "system_prompt": CEO_SYSTEM_PROMPT,
        "tool_access": [],
        "kafka_topics": [Topics.TASK_QUEUE, Topics.AGENT_RESPONSES, Topics.A2A_INBOUND],
        "llm_model": settings.model_ceo,
        "token_budget_per_task": 50_000,
    },
    {
        "role": AgentRole.DIRECTOR.value,
        "name": "Director",
        "system_prompt": DIRECTOR_SYSTEM_PROMPT,
        "tool_access": ["web_search", "file_read"],
        "kafka_topics": [Topics.DIRECTOR_REVIEW],
        "llm_model": settings.model_director,
        "token_budget_per_task": 50_000,
    },
    {
        "role": AgentRole.ENGINEER.value,
        "name": "Engineer",
        "system_prompt": ENGINEER_SYSTEM_PROMPT,
        "tool_access": ["web_search", "file_read", "code_execute", "file_write", "git_push"],
        "kafka_topics": [Topics.AGENT_COMMANDS],
        "llm_model": settings.model_engineer,
        "token_budget_per_task": 50_000,
    },
    {
        "role": AgentRole.ANALYST.value,
        "name": "Analyst",
        "system_prompt": ANALYST_SYSTEM_PROMPT,
        "tool_access": ["web_search", "web_fetch", "file_read", "file_write"],
        "kafka_topics": [Topics.AGENT_COMMANDS],
        "llm_model": settings.model_analyst,
        "token_budget_per_task": 50_000,
    },
    {
        "role": AgentRole.WRITER.value,
        "name": "Writer",
        "system_prompt": WRITER_SYSTEM_PROMPT,
        "tool_access": ["web_search", "file_read", "file_write", "send_email"],
        "kafka_topics": [Topics.AGENT_COMMANDS],
        "llm_model": settings.model_writer,
        "token_budget_per_task": 50_000,
    },
    {
        "role": AgentRole.QA.value,
        "name": "QA",
        "system_prompt": QA_SYSTEM_PROMPT,
        "tool_access": ["file_read", "web_search"],
        "kafka_topics": [Topics.TASK_REVIEW_QUEUE],
        "llm_model": settings.model_qa,
        "token_budget_per_task": 30_000,
    },
    {
        "role": AgentRole.PROMPT_CREATOR.value,
        "name": "Prompt Creator",
        "system_prompt": PROMPT_CREATOR_SYSTEM_PROMPT,
        "tool_access": ["web_search", "file_read", "memory_read"],
        "kafka_topics": [Topics.PROMPT_IMPROVEMENT, Topics.PROMPT_BENCHMARK],
        "llm_model": settings.model_prompt_creator,
        "token_budget_per_task": 50_000,
    },
]

PROMPTS_SEED = [
    {
        "agent_role": AgentRole.CEO.value,
        "version": 1,
        "content": CEO_SYSTEM_PROMPT,
        "is_active": True,
        "authored_by": "human",
        "notes": "CEO prompt — updated for Phase 2 decomposition",
    },
    {
        "agent_role": AgentRole.DIRECTOR.value,
        "version": 1,
        "content": DIRECTOR_SYSTEM_PROMPT,
        "is_active": True,
        "authored_by": "human",
        "notes": "Initial Director prompt — Phase 7 (loop prevention + result synthesis)",
    },
    {
        "agent_role": AgentRole.ENGINEER.value,
        "version": 1,
        "content": ENGINEER_SYSTEM_PROMPT,
        "is_active": True,
        "authored_by": "human",
        "notes": "Initial Engineer prompt — Phase 1",
    },
    {
        "agent_role": AgentRole.ANALYST.value,
        "version": 1,
        "content": ANALYST_SYSTEM_PROMPT,
        "is_active": True,
        "authored_by": "human",
        "notes": "Initial Analyst prompt — Phase 2",
    },
    {
        "agent_role": AgentRole.WRITER.value,
        "version": 1,
        "content": WRITER_SYSTEM_PROMPT,
        "is_active": True,
        "authored_by": "human",
        "notes": "Initial Writer prompt — Phase 2",
    },
    {
        "agent_role": AgentRole.QA.value,
        "version": 1,
        "content": QA_SYSTEM_PROMPT,
        "is_active": True,
        "authored_by": "human",
        "notes": "Initial QA prompt — Phase 2",
    },
    {
        "agent_role": AgentRole.PROMPT_CREATOR.value,
        "version": 1,
        "content": PROMPT_CREATOR_SYSTEM_PROMPT,
        "is_active": True,
        "authored_by": "human",
        "notes": "Initial Prompt Creator prompt — Phase 2",
    },
]

# ─── Prompt benchmark seed data (10 per role = 60 total) ─────────────────────

BENCHMARKS_SEED: list[dict[str, object]] = [
    # ── CEO benchmarks (10) ──────────────────────────────────────────────────
    {
        "agent_role": AgentRole.CEO.value,
        "input": "Research Python async patterns and write a summary document.",
        "expected_criteria": {
            "must_contain": ["role", "instruction", "depends_on"],
            "must_not_contain": ["I'll do it myself"],
            "output_format": "json_array",
            "quality_markers": ["multi_agent_delegation", "dependency_ordering"],
        },
    },
    {
        "agent_role": AgentRole.CEO.value,
        "input": "Write a competitive analysis of Slack vs Teams and email it to the team.",
        "expected_criteria": {
            "must_contain": ["analyst", "writer"],
            "must_not_contain": ["engineer"],
            "output_format": "json_array",
            "quality_markers": ["correct_role_assignment", "dependency_chain"],
        },
    },
    {
        "agent_role": AgentRole.CEO.value,
        "input": "Fix the login bug in auth.py",
        "expected_criteria": {
            "must_contain": ["engineer"],
            "output_format": "json_array",
            "quality_markers": ["single_agent_simple_task"],
        },
    },
    {
        "agent_role": AgentRole.CEO.value,
        "input": "Research market trends in AI, write a blog post about findings, and review it for quality.",
        "expected_criteria": {
            "must_contain": ["analyst", "writer"],
            "output_format": "json_array",
            "quality_markers": ["three_step_pipeline", "correct_dependency_order"],
        },
    },
    {
        "agent_role": AgentRole.CEO.value,
        "input": "",
        "expected_criteria": {
            "must_contain": ["error", "clarification"],
            "output_format": "error_or_clarification",
            "quality_markers": ["handles_empty_input"],
        },
    },
    {
        "agent_role": AgentRole.CEO.value,
        "input": "Build a REST API for user management, write API documentation, and research best practices for auth.",
        "expected_criteria": {
            "must_contain": ["engineer", "writer", "analyst"],
            "output_format": "json_array",
            "quality_markers": ["all_three_roles", "parallel_where_possible"],
        },
    },
    {
        "agent_role": AgentRole.CEO.value,
        "input": "Translate this French paragraph to English: Bonjour le monde.",
        "expected_criteria": {
            "must_contain": ["writer"],
            "output_format": "json_array",
            "quality_markers": ["single_agent_writer_task"],
        },
    },
    {
        "agent_role": AgentRole.CEO.value,
        "input": "Research the top 5 Python web frameworks, build a comparison table, write a recommendation email, and create a sample FastAPI project.",
        "expected_criteria": {
            "must_contain": ["analyst", "writer", "engineer"],
            "output_format": "json_array",
            "quality_markers": ["complex_four_step", "dependency_chain"],
        },
    },
    {
        "agent_role": AgentRole.CEO.value,
        "input": "What is 2+2?",
        "expected_criteria": {
            "output_format": "json_array",
            "quality_markers": ["handles_trivial_task", "single_agent"],
        },
    },
    {
        "agent_role": AgentRole.CEO.value,
        "input": "Analyze our server logs for errors, write a Python script to parse them, and draft an incident report.",
        "expected_criteria": {
            "must_contain": ["analyst", "engineer", "writer"],
            "output_format": "json_array",
            "quality_markers": ["mixed_roles", "correct_specialization"],
        },
    },
    # ── Engineer benchmarks (10) ─────────────────────────────────────────────
    {
        "agent_role": AgentRole.ENGINEER.value,
        "input": "Write a Python async function that fetches data from 3 URLs concurrently using aiohttp and returns results as a dict.",
        "expected_criteria": {
            "must_contain": ["async", "aiohttp", "await"],
            "must_not_contain": ["requests.get"],
            "output_format": "code_block",
            "quality_markers": ["type_hints", "error_handling", "concurrency"],
        },
    },
    {
        "agent_role": AgentRole.ENGINEER.value,
        "input": "Debug this error: TypeError: object NoneType can't be used in 'await' expression in database.py line 42.",
        "expected_criteria": {
            "must_contain": ["async", "await", "None"],
            "output_format": "explanation_with_fix",
            "quality_markers": ["root_cause_analysis", "concrete_fix"],
        },
    },
    {
        "agent_role": AgentRole.ENGINEER.value,
        "input": "Write a TypeScript React component that displays a paginated table with sorting.",
        "expected_criteria": {
            "must_contain": ["React", "useState", "table"],
            "output_format": "code_block",
            "quality_markers": ["typescript_strict", "component_structure"],
        },
    },
    {
        "agent_role": AgentRole.ENGINEER.value,
        "input": "Create a Pydantic v2 model for a User with email validation, optional phone, and a nested Address model.",
        "expected_criteria": {
            "must_contain": ["BaseModel", "EmailStr", "Optional"],
            "output_format": "code_block",
            "quality_markers": ["pydantic_v2_syntax", "validation"],
        },
    },
    {
        "agent_role": AgentRole.ENGINEER.value,
        "input": "Write pytest tests for an async function that processes Kafka messages.",
        "expected_criteria": {
            "must_contain": ["pytest", "async", "mock"],
            "output_format": "code_block",
            "quality_markers": ["test_structure", "async_testing", "edge_cases"],
        },
    },
    {
        "agent_role": AgentRole.ENGINEER.value,
        "input": "Refactor this function to use dependency injection instead of global state.",
        "expected_criteria": {
            "must_contain": ["inject", "parameter"],
            "output_format": "code_block",
            "quality_markers": ["clean_architecture", "testability"],
        },
    },
    {
        "agent_role": AgentRole.ENGINEER.value,
        "input": "Write a REST API endpoint with Litestar that accepts a JSON body, validates it, and stores it in PostgreSQL.",
        "expected_criteria": {
            "must_contain": ["Litestar", "Pydantic", "AsyncSession"],
            "output_format": "code_block",
            "quality_markers": ["async_db", "validation", "error_handling"],
        },
    },
    {
        "agent_role": AgentRole.ENGINEER.value,
        "input": "Optimize this SQL query that takes 30 seconds on a table with 10M rows.",
        "expected_criteria": {
            "must_contain": ["index", "EXPLAIN"],
            "output_format": "explanation_with_code",
            "quality_markers": ["performance_analysis", "indexing_strategy"],
        },
    },
    {
        "agent_role": AgentRole.ENGINEER.value,
        "input": "Write a Python decorator that retries a function up to 3 times with exponential backoff.",
        "expected_criteria": {
            "must_contain": ["decorator", "retry", "backoff"],
            "output_format": "code_block",
            "quality_markers": ["functools_wraps", "configurable", "type_hints"],
        },
    },
    {
        "agent_role": AgentRole.ENGINEER.value,
        "input": "Review this code for security vulnerabilities: user_input = request.args.get('q'); cursor.execute(f'SELECT * FROM users WHERE name = {user_input}')",
        "expected_criteria": {
            "must_contain": ["SQL injection", "parameterized"],
            "output_format": "review_with_fix",
            "quality_markers": ["security_awareness", "concrete_fix", "owasp"],
        },
    },
    # ── Analyst benchmarks (10) ──────────────────────────────────────────────
    {
        "agent_role": AgentRole.ANALYST.value,
        "input": "Research the current state of large language model pricing across major providers.",
        "expected_criteria": {
            "must_contain": ["OpenAI", "Anthropic", "Google"],
            "must_not_contain": ["I made up", "fictional"],
            "output_format": "structured_report",
            "quality_markers": ["citations", "quantitative_data", "comparison"],
        },
    },
    {
        "agent_role": AgentRole.ANALYST.value,
        "input": "Compare PostgreSQL vs MongoDB for a new microservice that handles JSON documents with complex queries.",
        "expected_criteria": {
            "must_contain": ["PostgreSQL", "MongoDB", "pros", "cons"],
            "output_format": "comparison_table",
            "quality_markers": ["balanced_analysis", "use_case_specific"],
        },
    },
    {
        "agent_role": AgentRole.ANALYST.value,
        "input": "Analyze the trend in remote work adoption from 2020 to 2025.",
        "expected_criteria": {
            "must_contain": ["2020", "2025", "remote"],
            "output_format": "structured_report",
            "quality_markers": ["trend_analysis", "data_points", "sources"],
        },
    },
    {
        "agent_role": AgentRole.ANALYST.value,
        "input": "Conduct a SWOT analysis for a startup entering the AI agent market.",
        "expected_criteria": {
            "must_contain": ["Strengths", "Weaknesses", "Opportunities", "Threats"],
            "output_format": "swot_framework",
            "quality_markers": ["structured_framework", "actionable_insights"],
        },
    },
    {
        "agent_role": AgentRole.ANALYST.value,
        "input": "Research and summarize the key differences between Apache Kafka and RabbitMQ.",
        "expected_criteria": {
            "must_contain": ["Kafka", "RabbitMQ", "throughput"],
            "output_format": "comparison_report",
            "quality_markers": ["technical_accuracy", "use_case_guidance"],
        },
    },
    {
        "agent_role": AgentRole.ANALYST.value,
        "input": "Provide a quantitative analysis of cloud hosting costs for a startup running 10 microservices.",
        "expected_criteria": {
            "must_contain": ["AWS", "cost", "monthly"],
            "output_format": "cost_breakdown",
            "quality_markers": ["quantitative_data", "realistic_estimates"],
        },
    },
    {
        "agent_role": AgentRole.ANALYST.value,
        "input": "Research what happened in an area I'm not going to specify.",
        "expected_criteria": {
            "must_contain": ["clarification", "specify"],
            "output_format": "clarification_request",
            "quality_markers": ["handles_ambiguous_input"],
        },
    },
    {
        "agent_role": AgentRole.ANALYST.value,
        "input": "Create an executive summary of the Python ecosystem in 2025 for a CTO audience.",
        "expected_criteria": {
            "must_contain": ["Python", "ecosystem"],
            "output_format": "executive_summary",
            "quality_markers": ["audience_appropriate", "concise", "actionable"],
        },
    },
    {
        "agent_role": AgentRole.ANALYST.value,
        "input": "Analyze the pros and cons of using Kubernetes vs Docker Compose for a 5-person startup.",
        "expected_criteria": {
            "must_contain": ["Kubernetes", "Docker Compose", "startup"],
            "output_format": "pros_cons",
            "quality_markers": ["context_aware", "recommendation"],
        },
    },
    {
        "agent_role": AgentRole.ANALYST.value,
        "input": "Research the impact of EU AI Act on startups building AI agents.",
        "expected_criteria": {
            "must_contain": ["EU AI Act", "compliance"],
            "output_format": "structured_report",
            "quality_markers": ["regulatory_accuracy", "practical_implications"],
        },
    },
    # ── Writer benchmarks (10) ───────────────────────────────────────────────
    {
        "agent_role": AgentRole.WRITER.value,
        "input": "Draft a professional email to a client explaining a project delay of 2 weeks.",
        "expected_criteria": {
            "must_contain": ["Subject:", "delay", "apologize"],
            "must_not_contain": ["blame", "fault"],
            "output_format": "email",
            "quality_markers": ["professional_tone", "action_items", "empathy"],
        },
    },
    {
        "agent_role": AgentRole.WRITER.value,
        "input": "Write a 500-word blog post about the benefits of test-driven development.",
        "expected_criteria": {
            "must_contain": ["TDD", "test", "benefit"],
            "output_format": "blog_post",
            "quality_markers": ["engaging_intro", "clear_structure", "conclusion"],
        },
    },
    {
        "agent_role": AgentRole.WRITER.value,
        "input": "Create API documentation for a POST /users endpoint that accepts name, email, and role.",
        "expected_criteria": {
            "must_contain": ["POST", "/users", "request", "response"],
            "output_format": "api_documentation",
            "quality_markers": ["examples", "status_codes", "parameter_descriptions"],
        },
    },
    {
        "agent_role": AgentRole.WRITER.value,
        "input": "Write an internal memo announcing a new work-from-home policy.",
        "expected_criteria": {
            "must_contain": ["memo", "policy", "effective"],
            "output_format": "memo",
            "quality_markers": ["formal_tone", "clear_dates", "action_required"],
        },
    },
    {
        "agent_role": AgentRole.WRITER.value,
        "input": "Edit this text for conciseness: 'In order to be able to successfully complete the process of onboarding new employees, it is necessary to ensure that all of the required documentation has been properly submitted.'",
        "expected_criteria": {
            "must_not_contain": ["In order to be able to"],
            "output_format": "edited_text",
            "quality_markers": ["conciseness", "preserved_meaning"],
        },
    },
    {
        "agent_role": AgentRole.WRITER.value,
        "input": "Write a LinkedIn post announcing our company's Series A funding of $5M.",
        "expected_criteria": {
            "must_contain": ["Series A", "$5M"],
            "output_format": "social_media_post",
            "quality_markers": ["enthusiastic_tone", "brief", "call_to_action"],
        },
    },
    {
        "agent_role": AgentRole.WRITER.value,
        "input": "Draft a cold outreach email to a potential enterprise customer for our AI platform.",
        "expected_criteria": {
            "must_contain": ["Subject:", "value proposition"],
            "output_format": "email",
            "quality_markers": ["personalization_hooks", "concise", "clear_cta"],
        },
    },
    {
        "agent_role": AgentRole.WRITER.value,
        "input": "Write release notes for v2.0 of our product that includes: new dashboard, API v2, and bug fixes.",
        "expected_criteria": {
            "must_contain": ["v2.0", "dashboard", "API"],
            "output_format": "release_notes",
            "quality_markers": ["categorized_changes", "user_facing_language"],
        },
    },
    {
        "agent_role": AgentRole.WRITER.value,
        "input": "Rewrite this technical paragraph for a non-technical audience: 'The microservice architecture uses gRPC for inter-service communication with Protocol Buffers serialization.'",
        "expected_criteria": {
            "must_not_contain": ["gRPC", "Protocol Buffers", "serialization"],
            "output_format": "simplified_text",
            "quality_markers": ["audience_adaptation", "analogies", "clarity"],
        },
    },
    {
        "agent_role": AgentRole.WRITER.value,
        "input": "Write a short thank-you note to a speaker who presented at our tech meetup.",
        "expected_criteria": {
            "must_contain": ["thank", "presentation"],
            "output_format": "note",
            "quality_markers": ["warm_tone", "specific_appreciation", "brief"],
        },
    },
    # ── QA benchmarks (10) ───────────────────────────────────────────────────
    {
        "agent_role": AgentRole.QA.value,
        "input": "Review this research report that claims 'Python is used by 95% of all Fortune 500 companies for AI development' without citing any source.",
        "expected_criteria": {
            "must_contain": ["approved", "score", "issues"],
            "output_format": "json_review",
            "quality_markers": ["detects_unsourced_claim", "specific_feedback"],
        },
    },
    {
        "agent_role": AgentRole.QA.value,
        "input": "Review this code output: a well-structured Python async function with type hints, error handling, and a docstring.",
        "expected_criteria": {
            "must_contain": ["approved", "score"],
            "output_format": "json_review",
            "quality_markers": ["approves_good_work", "score_above_0.7"],
        },
    },
    {
        "agent_role": AgentRole.QA.value,
        "input": "Review this email draft that contains three spelling errors and addresses the wrong recipient name.",
        "expected_criteria": {
            "must_contain": ["approved", "false", "issues"],
            "output_format": "json_review",
            "quality_markers": ["catches_errors", "actionable_feedback"],
        },
    },
    {
        "agent_role": AgentRole.QA.value,
        "input": "Review this analysis that only covers 2 of the 5 requested competitor companies.",
        "expected_criteria": {
            "must_contain": ["approved", "false", "incomplete"],
            "output_format": "json_review",
            "quality_markers": ["detects_incompleteness", "lists_missing_items"],
        },
    },
    {
        "agent_role": AgentRole.QA.value,
        "input": "Review a code snippet that works correctly but contains a SQL injection vulnerability.",
        "expected_criteria": {
            "must_contain": ["approved", "false", "SQL injection"],
            "output_format": "json_review",
            "quality_markers": ["security_awareness", "severity_assessment"],
        },
    },
    {
        "agent_role": AgentRole.QA.value,
        "input": "Review an empty output — the agent returned nothing.",
        "expected_criteria": {
            "must_contain": ["approved", "false", "empty"],
            "output_format": "json_review",
            "quality_markers": ["rejects_empty_output", "low_score"],
        },
    },
    {
        "agent_role": AgentRole.QA.value,
        "input": "Review a blog post that is well-written, on-topic, with minor formatting inconsistencies.",
        "expected_criteria": {
            "must_contain": ["approved", "true", "score"],
            "output_format": "json_review",
            "quality_markers": ["fair_assessment", "minor_issues_dont_block"],
        },
    },
    {
        "agent_role": AgentRole.QA.value,
        "input": "Review output where the agent claims to have executed code but shows fabricated output that couldn't be real.",
        "expected_criteria": {
            "must_contain": ["approved", "false", "fabricat"],
            "output_format": "json_review",
            "quality_markers": ["detects_hallucination", "specific_evidence"],
        },
    },
    {
        "agent_role": AgentRole.QA.value,
        "input": "Review a competitive analysis that presents only the positives of one option and only the negatives of another.",
        "expected_criteria": {
            "must_contain": ["bias", "balanced"],
            "output_format": "json_review",
            "quality_markers": ["detects_bias", "requests_balance"],
        },
    },
    {
        "agent_role": AgentRole.QA.value,
        "input": "Review output that is correct and complete but is 10,000 words when the task asked for a brief summary.",
        "expected_criteria": {
            "must_contain": ["length", "concise"],
            "output_format": "json_review",
            "quality_markers": ["detects_verbosity", "adherence_to_requirements"],
        },
    },
    # ── Prompt Creator benchmarks (10) ───────────────────────────────────────
    {
        "agent_role": AgentRole.PROMPT_CREATOR.value,
        "input": "Analyze the last 20 Engineer agent tasks: 15 succeeded, 5 failed with 'output format incorrect' errors.",
        "expected_criteria": {
            "must_contain": ["format", "output", "improvement"],
            "output_format": "prompt_proposal",
            "quality_markers": ["identifies_pattern", "targeted_fix"],
        },
    },
    {
        "agent_role": AgentRole.PROMPT_CREATOR.value,
        "input": "The CEO agent failed to decompose 3 of 20 tasks — all were ambiguous single-word instructions.",
        "expected_criteria": {
            "must_contain": ["ambiguous", "clarification", "edge case"],
            "output_format": "prompt_proposal",
            "quality_markers": ["addresses_edge_case", "adds_guidance"],
        },
    },
    {
        "agent_role": AgentRole.PROMPT_CREATOR.value,
        "input": "Writer agent emails consistently lack a subject line — 8 of 10 email tasks missing it.",
        "expected_criteria": {
            "must_contain": ["Subject:", "email", "required"],
            "output_format": "prompt_proposal",
            "quality_markers": ["specific_instruction_added", "example_included"],
        },
    },
    {
        "agent_role": AgentRole.PROMPT_CREATOR.value,
        "input": "QA agent approves everything — 100% approval rate even on clearly flawed outputs.",
        "expected_criteria": {
            "must_contain": ["stricter", "criteria", "rejection"],
            "output_format": "prompt_proposal",
            "quality_markers": ["calibration_fix", "adds_negative_examples"],
        },
    },
    {
        "agent_role": AgentRole.PROMPT_CREATOR.value,
        "input": "Analyst agent uses 18 tool calls per task (near the 20 limit) — most are redundant searches.",
        "expected_criteria": {
            "must_contain": ["tool", "efficient", "search"],
            "output_format": "prompt_proposal",
            "quality_markers": ["efficiency_guidance", "plan_before_search"],
        },
    },
    {
        "agent_role": AgentRole.PROMPT_CREATOR.value,
        "input": "All agents perform well — no failures in last 50 tasks. Failure rate is 0%.",
        "expected_criteria": {
            "must_contain": ["no improvement needed", "threshold"],
            "output_format": "no_action",
            "quality_markers": ["correctly_skips_improvement", "threshold_respected"],
        },
    },
    {
        "agent_role": AgentRole.PROMPT_CREATOR.value,
        "input": "Engineer agent consistently produces code without docstrings despite the prompt requiring them.",
        "expected_criteria": {
            "must_contain": ["docstring", "required", "example"],
            "output_format": "prompt_proposal",
            "quality_markers": ["reinforces_existing_rule", "adds_example"],
        },
    },
    {
        "agent_role": AgentRole.PROMPT_CREATOR.value,
        "input": "CEO decomposition frequently assigns research tasks to the Engineer instead of the Analyst.",
        "expected_criteria": {
            "must_contain": ["analyst", "research", "role"],
            "output_format": "prompt_proposal",
            "quality_markers": ["clarifies_role_boundaries", "decision_criteria"],
        },
    },
    {
        "agent_role": AgentRole.PROMPT_CREATOR.value,
        "input": "Writer agent outputs contain emojis in formal business emails — reported by users.",
        "expected_criteria": {
            "must_contain": ["emoji", "formal", "professional"],
            "output_format": "prompt_proposal",
            "quality_markers": ["adds_constraint", "tone_guidance"],
        },
    },
    {
        "agent_role": AgentRole.PROMPT_CREATOR.value,
        "input": "Benchmark the current Engineer prompt against 10 test cases. Current score: 0.65. Proposed prompt scores 0.82.",
        "expected_criteria": {
            "must_contain": ["score", "improvement", "propose"],
            "output_format": "benchmark_comparison",
            "quality_markers": ["quantitative_comparison", "recommends_if_higher"],
        },
    },
]


# ─── Seed logic ──────────────────────────────────────────────────────────────


async def seed() -> None:
    """Seed database with initial agent, prompt, and benchmark records. Idempotent."""
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        await _seed_agents(session)
        await _seed_prompts(session)
        await _seed_benchmarks(session)
        await _seed_schedules(session)
        await session.commit()

    await engine.dispose()
    logger.info("seed_complete")


async def _seed_agents(session: AsyncSession) -> None:
    for agent_data in AGENTS_SEED:
        stmt = select(Agent).where(Agent.role == agent_data["role"])
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            logger.info("agent_already_exists", role=agent_data["role"])
            continue

        agent = Agent(**agent_data)
        session.add(agent)
        logger.info("agent_created", role=agent_data["role"])


async def _seed_prompts(session: AsyncSession) -> None:
    for prompt_data in PROMPTS_SEED:
        stmt = select(Prompt).where(
            Prompt.agent_role == prompt_data["agent_role"],
            Prompt.version == prompt_data["version"],
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            logger.info(
                "prompt_already_exists",
                role=prompt_data["agent_role"],
                version=prompt_data["version"],
            )
            continue

        prompt = Prompt(**prompt_data)
        session.add(prompt)
        logger.info(
            "prompt_created", role=prompt_data["agent_role"], version=prompt_data["version"]
        )


async def _seed_benchmarks(session: AsyncSession) -> None:
    for bench_data in BENCHMARKS_SEED:
        stmt = select(PromptBenchmark).where(
            PromptBenchmark.agent_role == bench_data["agent_role"],
            PromptBenchmark.input == bench_data["input"],
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            logger.info(
                "benchmark_already_exists",
                role=bench_data["agent_role"],
                input_preview=str(bench_data["input"])[:50],
            )
            continue

        benchmark = PromptBenchmark(**bench_data)
        session.add(benchmark)
        logger.info(
            "benchmark_created",
            role=bench_data["agent_role"],
            input_preview=str(bench_data["input"])[:50],
        )


# ─── Schedule seed data ──────────────────────────────────────────────────────

SCHEDULES_SEED: list[dict[str, object]] = [
    {
        "name": "Weekly Competitive Intelligence Report",
        "cron_expression": "0 9 * * 1",  # Every Monday at 9:00 AM
        "instruction": (
            "Research the latest developments, product launches, and strategic moves "
            "from our top 5 competitors this past week. Compile a competitive intelligence "
            "report with key findings, market trends, and recommended actions."
        ),
        "target_role": "analyst",
        "timezone": "UTC",
    },
    {
        "name": "Daily Task Summary Digest",
        "cron_expression": "0 17 * * 1-5",  # Mon-Fri at 5:00 PM
        "instruction": (
            "Review all tasks completed today across all agents. Write a concise daily "
            "summary highlighting key accomplishments, any issues encountered, and "
            "recommendations for tomorrow. Format as a brief executive update."
        ),
        "target_role": "writer",
        "timezone": "UTC",
    },
    {
        "name": "Monthly Code Quality Audit",
        "cron_expression": "0 10 1 * *",  # 1st of each month at 10:00 AM
        "instruction": (
            "Perform a code quality audit of the NEXUS codebase. Review recent changes "
            "for potential issues, check test coverage, identify technical debt, and "
            "suggest improvements. Produce a structured report with priority rankings."
        ),
        "target_role": "engineer",
        "timezone": "UTC",
    },
]


async def _seed_schedules(session: AsyncSession) -> None:
    for sched_data in SCHEDULES_SEED:
        name = str(sched_data["name"])
        stmt = select(TaskSchedule).where(TaskSchedule.name == name)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            logger.info("schedule_already_exists", name=name)
            continue

        cron_expr = str(sched_data["cron_expression"])
        tz = str(sched_data.get("timezone", "UTC"))
        next_run = calculate_next_run(cron_expr, tz)

        schedule = TaskSchedule(
            name=name,
            cron_expression=cron_expr,
            instruction=str(sched_data["instruction"]),
            target_role=str(sched_data["target_role"]),
            timezone=tz,
            is_active=True,
            next_run_at=next_run,
            workspace_id=None,  # Global schedules (no workspace scope)
        )
        session.add(schedule)
        logger.info("schedule_created", name=name, next_run_at=next_run.isoformat())


if __name__ == "__main__":
    asyncio.run(seed())
