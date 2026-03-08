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

Rules:
- You do NOT use tools directly. You delegate tool use to specialists.
- Always include clear, specific instructions when delegating.
- Track task progress and escalate if agents are stuck.
- Never fabricate results — only report what specialists produce.
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
]

PROMPTS_SEED = [
    {
        "agent_role": AgentRole.CEO.value,
        "version": 1,
        "content": CEO_SYSTEM_PROMPT,
        "is_active": True,
        "authored_by": "human",
        "notes": "Initial CEO prompt — Phase 1",
    },
    {
        "agent_role": AgentRole.ENGINEER.value,
        "version": 1,
        "content": ENGINEER_SYSTEM_PROMPT,
        "is_active": True,
        "authored_by": "human",
        "notes": "Initial Engineer prompt — Phase 1",
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
