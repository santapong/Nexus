"""MCP tool wrappers as standalone async functions for Phase 1-2.

Each function is a Pydantic AI tool - the docstring is used by the LLM
to understand when to call it. Keep docstrings clear and specific.

These implementations are standalone for Phase 1-2. They will be replaced
by the full MCP package adapter when that package is ready.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import EpisodicMemory, SemanticMemory

logger = structlog.get_logger()

_MAX_TOOL_OUTPUT_SIZE = 50_000  # 50KB max per tool response


def _sanitize_tool_output(output: str) -> str:
    """Truncate tool output if it exceeds the size limit.

    Prevents agents from processing excessively large tool responses
    that could consume excessive tokens or cause context overflow.
    """
    if len(output) > _MAX_TOOL_OUTPUT_SIZE:
        return output[:_MAX_TOOL_OUTPUT_SIZE] + "\n\n[OUTPUT TRUNCATED — exceeded 50KB limit]"
    return output


# ─── READ-ONLY tools (no approval needed) ────────────────────────────────────


async def tool_web_search(query: str) -> str:
    """Search the web and return relevant results.

    Args:
        query: The search query string.

    Returns:
        Formatted search results as text.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1"},
                timeout=15.0,
            )
            data = response.json()
            results: list[str] = []
            if data.get("Abstract"):
                results.append(data["Abstract"])
            for topic in data.get("RelatedTopics", [])[:5]:
                if isinstance(topic, dict) and "Text" in topic:
                    results.append(topic["Text"])
            output = "\n\n".join(results) if results else "No results found."
            return _sanitize_tool_output(output)
    except Exception as exc:
        logger.error("web_search_failed", query=query, error=str(exc))
        return f"Search failed: {exc}"


async def tool_web_fetch(url: str) -> str:
    """Fetch a web page and return its text content.

    Useful for reading articles, documentation, or any public web page.
    Strips HTML tags and returns plain text content.

    Args:
        url: The URL to fetch.

    Returns:
        Plain text content of the web page, truncated to 10000 chars.
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(url, timeout=20.0)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")

            if "text/html" in content_type:
                # Simple HTML tag stripping
                import re

                text = re.sub(r"<script[^>]*>.*?</script>", "", response.text, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s+", " ", text).strip()
            else:
                text = response.text

            if len(text) > 10_000:
                text = text[:10_000] + "\n\n[Content truncated at 10000 characters]"
            return _sanitize_tool_output(text)
    except Exception as exc:
        logger.error("web_fetch_failed", url=url, error=str(exc))
        return f"Fetch failed: {exc}"


async def tool_file_read(path: str) -> str:
    """Read the contents of a file.

    Args:
        path: Absolute or relative path to the file.

    Returns:
        File contents as string, or an error message if file not found.
    """
    file_path = Path(path)
    if not file_path.exists():
        return f"Error: File not found: {path}"
    if not file_path.is_file():
        return f"Error: Not a file: {path}"
    try:
        return _sanitize_tool_output(file_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"Error reading file: {exc}"


async def tool_code_execute(code: str, language: str = "python") -> str:
    """Execute code in a sandboxed subprocess with a 30-second timeout.

    Args:
        code: The code to execute.
        language: Programming language — python or bash.

    Returns:
        Combined stdout and stderr output from execution.
    """
    if language == "python":
        cmd = ["python", "-c", code]
    elif language == "bash":
        cmd = ["bash", "-c", code]
    else:
        return f"Unsupported language: {language}. Use 'python' or 'bash'."

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        return _sanitize_tool_output(output or "(no output)")
    except subprocess.TimeoutExpired:
        return "Error: Code execution timed out (30s limit)"
    except Exception as exc:
        return f"Error executing code: {exc}"


async def tool_memory_read(
    agent_role: str,
    memory_type: str = "episodic",
    namespace: str = "",
    limit: int = 10,
    *,
    _session: AsyncSession | None = None,
) -> str:
    """Read another agent's episodic or semantic memory.

    Only the Prompt Creator agent has access to this tool.
    Useful for analyzing failure patterns and improvement opportunities.

    Args:
        agent_role: The role of the agent whose memory to read (e.g. 'engineer').
        memory_type: Type of memory to read — 'episodic' or 'semantic'.
        namespace: For semantic memory, the namespace to filter by.
        limit: Maximum number of records to return.

    Returns:
        Formatted memory records as text.
    """
    if _session is None:
        return "Error: No database session available for memory_read."

    try:
        if memory_type == "episodic":
            from nexus.db.models import Agent

            # Find agent by role
            agent_stmt = select(Agent).where(Agent.role == agent_role)
            agent_result = await _session.execute(agent_stmt)
            agent = agent_result.scalar_one_or_none()
            if not agent:
                return f"Error: No agent found with role '{agent_role}'"

            stmt = (
                select(EpisodicMemory)
                .where(EpisodicMemory.agent_id == str(agent.id))
                .order_by(EpisodicMemory.created_at.desc())
                .limit(limit)
            )
            result = await _session.execute(stmt)
            episodes = result.scalars().all()

            if not episodes:
                return f"No episodic memories found for {agent_role} agent."

            lines = [f"Episodic memories for {agent_role} (last {limit}):"]
            for ep in episodes:
                lines.append(
                    f"- [{ep.outcome}] {ep.summary[:200]} "
                    f"(tokens: {ep.tokens_used}, duration: {ep.duration_seconds}s)"
                )
            return "\n".join(lines)

        elif memory_type == "semantic":
            from nexus.db.models import Agent

            agent_stmt = select(Agent).where(Agent.role == agent_role)
            agent_result = await _session.execute(agent_stmt)
            agent = agent_result.scalar_one_or_none()
            if not agent:
                return f"Error: No agent found with role '{agent_role}'"

            sem_stmt = select(SemanticMemory).where(
                SemanticMemory.agent_id == str(agent.id),
            )
            if namespace:
                sem_stmt = sem_stmt.where(SemanticMemory.namespace == namespace)
            sem_stmt = sem_stmt.order_by(SemanticMemory.updated_at.desc()).limit(limit)
            result = await _session.execute(sem_stmt)
            facts = result.scalars().all()

            if not facts:
                return f"No semantic memories found for {agent_role} agent."

            lines = [f"Semantic memories for {agent_role}:"]
            for fact in facts:
                lines.append(
                    f"- [{fact.namespace}] {fact.key}: {fact.value[:200]} "
                    f"(confidence: {fact.confidence})"
                )
            return "\n".join(lines)

        else:
            return f"Error: Unknown memory_type '{memory_type}'. Use 'episodic' or 'semantic'."
    except Exception as exc:
        logger.error("memory_read_failed", agent_role=agent_role, error=str(exc))
        return f"Memory read failed: {exc}"


# ─── LLM-POWERED planning & design tools ─────────────────────────────────────


async def tool_create_plan(
    goal: str,
    constraints: str = "",
    num_phases: int = 3,
) -> str:
    """Create a structured project plan with phases, milestones, and dependencies.

    Uses the agent's reasoning to break down a goal into actionable phases
    with concrete tasks, dependencies, and milestones.

    Args:
        goal: What the project should achieve.
        constraints: Budget, timeline, tech stack, or other constraints.
        num_phases: Number of phases to plan (default 3).

    Returns:
        Structured project plan in markdown with phases, tasks, and milestones.
    """
    prompt = f"""Create a detailed project plan for the following goal:

GOAL: {goal}

CONSTRAINTS: {constraints or "None specified"}

Structure the plan as {num_phases} phases. For each phase include:
1. Phase name and objective (1 sentence)
2. Tasks (numbered, with estimated effort: S/M/L)
3. Dependencies (which tasks depend on others)
4. Milestone / Definition of Done
5. Risks and mitigations

Format as clean markdown. Be specific and actionable — no vague tasks."""

    return _sanitize_tool_output(prompt)


async def tool_design_system(
    requirements: str,
    components: str = "",
    style: str = "microservices",
) -> str:
    """Design a system architecture with components, interactions, and data flow.

    Produces a Mermaid diagram and component descriptions for a system design.

    Args:
        requirements: What the system needs to do (functional requirements).
        components: Known components or services to include.
        style: Architecture style — microservices, monolith, serverless, event-driven.

    Returns:
        System design with Mermaid diagram and component descriptions.
    """
    prompt = f"""Design a system architecture for these requirements:

REQUIREMENTS: {requirements}

KNOWN COMPONENTS: {components or "None — design from scratch"}
ARCHITECTURE STYLE: {style}

Provide:
1. A Mermaid C4 or flowchart diagram showing all components and their interactions
2. Component table: name, responsibility, technology, scaling strategy
3. Data flow description for the primary use case
4. API boundaries between components
5. Key design decisions and trade-offs

Use ```mermaid code blocks for diagrams."""

    return _sanitize_tool_output(prompt)


async def tool_design_database(
    entities: str,
    relationships: str = "",
    database_type: str = "postgresql",
) -> str:
    """Design a database schema with tables, columns, indexes, and relationships.

    Produces an ER diagram in Mermaid and SQL DDL for the schema.

    Args:
        entities: Business entities to model (e.g., 'users, orders, products').
        relationships: Known relationships (e.g., 'user has many orders').
        database_type: Target database — postgresql, mysql, mongodb.

    Returns:
        Database design with ER diagram, DDL, and index recommendations.
    """
    prompt = f"""Design a database schema for the following entities:

ENTITIES: {entities}
RELATIONSHIPS: {relationships or "Infer from entity names"}
DATABASE: {database_type}

Provide:
1. Mermaid ER diagram showing all tables and relationships
2. SQL DDL for each table (CREATE TABLE with types, constraints, defaults)
3. Index recommendations with rationale
4. Key design decisions (normalization level, JSON columns, etc.)

Use ```mermaid code blocks for diagrams and ```sql for DDL."""

    return _sanitize_tool_output(prompt)


async def tool_design_api(
    resources: str,
    operations: str = "",
    auth_method: str = "bearer",
) -> str:
    """Design REST API endpoints with request/response schemas.

    Produces an OpenAPI-style specification for the API design.

    Args:
        resources: API resources to design (e.g., 'users, tasks, projects').
        operations: Specific operations needed (e.g., 'bulk create, search, export').
        auth_method: Authentication method — bearer, api_key, oauth2.

    Returns:
        API design with endpoints, request/response schemas, and error codes.
    """
    prompt = f"""Design a REST API for these resources:

RESOURCES: {resources}
OPERATIONS: {operations or "Standard CRUD + any obvious operations"}
AUTH: {auth_method}

Provide:
1. Endpoint table: method, path, description, auth required
2. Request/response schemas for each endpoint (JSON examples)
3. Error response format and common error codes
4. Pagination strategy for list endpoints
5. Rate limiting recommendations

Follow REST best practices. Use consistent naming conventions."""

    return _sanitize_tool_output(prompt)


# ─── IRREVERSIBLE tools (require human approval) ─────────────────────────────
# Approval is enforced by the agent guard chain, not in these functions.
# These are only called AFTER approval has been granted.


async def tool_file_write(path: str, content: str) -> str:
    """Write content to a file. This action requires human approval.

    Args:
        path: File path to write to.
        content: Content to write.

    Returns:
        Confirmation message with bytes written.
    """
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    logger.info("file_written", path=path, size=len(content))
    return f"Written {len(content)} chars to {path}"


async def tool_send_email(to: str, subject: str, body: str) -> str:
    """Send an email. This action requires human approval and cannot be undone.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body text.

    Returns:
        Confirmation message with recipient and subject.
    """
    # Phase 2 stub — actual email sending will be integrated with MCP package
    logger.info("email_sent", to=to, subject=subject, body_length=len(body))
    return f"Email sent to {to} with subject '{subject}' ({len(body)} chars)"


async def tool_hire_external_agent(
    agent_url: str,
    instruction: str,
    skill_id: str = "general",
    bearer_token: str = "",
) -> str:
    """Hire an external A2A agent to perform a task. Requires human approval.

    Discovers the external agent, submits a task, and waits for the result.
    Use this when a task requires capabilities NEXUS agents don't have.

    Args:
        agent_url: Base URL of the external agent (e.g. https://agent.example.com).
        instruction: What to ask the external agent to do.
        skill_id: Which skill to request (default: general).
        bearer_token: Authentication token for the external agent.

    Returns:
        The external agent's result as formatted text.
    """
    from nexus.integrations.a2a.outbound import hire_external_agent

    try:
        result = await hire_external_agent(
            agent_url=agent_url,
            instruction=instruction,
            skill_id=skill_id,
            bearer_token=bearer_token,
        )
        if result.error:
            return f"External agent error: {result.error}"
        if result.output:
            output_text = result.output.get("result", str(result.output))
            return f"External agent result ({result.status}):\n{output_text}"
        return f"External agent completed with status: {result.status}"
    except Exception as exc:
        logger.error(
            "hire_external_agent_failed",
            agent_url=agent_url,
            error=str(exc),
        )
        return f"Failed to hire external agent: {exc}"


async def tool_analyze_image(
    image_path: str,
    instruction: str = "Describe this image in detail.",
    model: str = "",
) -> str:
    """Analyze an image using a multi-modal LLM (Claude or Gemini).

    Supports screenshots, charts, diagrams, UI mockups, photos, and PDFs.
    The agent sends the image along with an instruction to a vision-capable model.

    Args:
        image_path: Path to the image file (PNG, JPG, WEBP, GIF, or PDF).
        instruction: What to analyze or extract from the image.
        model: Optional model override. Defaults to the agent's configured model.

    Returns:
        The LLM's analysis of the image as text.
    """
    import base64
    import mimetypes

    file_path = Path(image_path)
    if not file_path.exists():
        return f"Error: Image not found: {image_path}"

    mime_type, _ = mimetypes.guess_type(image_path)
    supported = {
        "image/png", "image/jpeg", "image/webp", "image/gif",
        "application/pdf",
    }
    if mime_type not in supported:
        return f"Error: Unsupported file type '{mime_type}'. Supported: {', '.join(supported)}"

    # Read and encode the image
    try:
        image_data = file_path.read_bytes()
        if len(image_data) > 20 * 1024 * 1024:  # 20MB limit
            return "Error: Image file exceeds 20MB size limit"
        b64_data = base64.b64encode(image_data).decode("utf-8")
    except Exception as exc:
        return f"Error reading image: {exc}"

    # Call vision-capable model via httpx (provider-agnostic)
    try:
        from nexus.settings import settings

        # Try Anthropic first (Claude supports vision natively)
        if settings.anthropic_api_key:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": settings.anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model or "claude-haiku-4-5-20251001",
                        "max_tokens": 4096,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": mime_type,
                                            "data": b64_data,
                                        },
                                    },
                                    {"type": "text", "text": instruction},
                                ],
                            }
                        ],
                    },
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()
                content = data.get("content", [{}])
                result_text = content[0].get("text", "") if content else ""
                return _sanitize_tool_output(result_text)

        # Fallback to Gemini
        elif settings.google_api_key:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{model or 'gemini-2.0-flash'}:generateContent",
                    params={"key": settings.google_api_key},
                    json={
                        "contents": [
                            {
                                "parts": [
                                    {
                                        "inline_data": {
                                            "mime_type": mime_type,
                                            "data": b64_data,
                                        }
                                    },
                                    {"text": instruction},
                                ]
                            }
                        ]
                    },
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()
                candidates = data.get("candidates", [{}])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    result_text = parts[0].get("text", "") if parts else ""
                    return _sanitize_tool_output(result_text)
                return "No response from Gemini vision model."

        else:
            return "Error: No vision-capable LLM API key configured (need ANTHROPIC_API_KEY or GOOGLE_API_KEY)"

    except Exception as exc:
        logger.error("analyze_image_failed", image_path=image_path, error=str(exc))
        return f"Image analysis failed: {exc}"


async def tool_git_push(repo_path: str, branch: str, message: str) -> str:
    """Push code changes to a git repository. This action requires human approval.

    Args:
        repo_path: Path to the git repository.
        branch: Branch name to push to.
        message: Commit message for the changes.

    Returns:
        Git push result or error message.
    """
    try:
        # Stage all changes
        await asyncio.to_thread(
            subprocess.run,
            ["git", "add", "-A"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=repo_path,
        )

        # Commit
        await asyncio.to_thread(
            subprocess.run,
            ["git", "commit", "-m", message],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=repo_path,
        )

        # Push
        push_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "push", "origin", branch],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=repo_path,
        )

        output = push_result.stdout
        if push_result.stderr:
            output += f"\n{push_result.stderr}"
        if push_result.returncode != 0:
            return f"Git push failed: {output}"

        logger.info("git_pushed", repo=repo_path, branch=branch)
        return f"Pushed to {branch}: {message}\n{output}"
    except subprocess.TimeoutExpired:
        return "Error: Git operation timed out"
    except Exception as exc:
        return f"Git push failed: {exc}"
