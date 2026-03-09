"""Database seed script. Run with: python -m nexus.db.seed"""
from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.db.models import Agent, AgentRole, Prompt
from nexus.kafka.topics import Topics
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
]


# ─── Seed logic ──────────────────────────────────────────────────────────────


async def seed() -> None:
    """Seed database with initial agent and prompt records. Idempotent."""
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        await _seed_agents(session)
        await _seed_prompts(session)
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
            logger.info("prompt_already_exists", role=prompt_data["agent_role"], version=prompt_data["version"])
            continue

        prompt = Prompt(**prompt_data)
        session.add(prompt)
        logger.info("prompt_created", role=prompt_data["agent_role"], version=prompt_data["version"])


if __name__ == "__main__":
    asyncio.run(seed())
