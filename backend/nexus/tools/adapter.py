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
            return "\n\n".join(results) if results else "No results found."
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

                text = re.sub(r"<script[^>]*>.*?</script>", "", response.text, flags=re.DOTALL)
                text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s+", " ", text).strip()
            else:
                text = response.text

            if len(text) > 10_000:
                text = text[:10_000] + "\n\n[Content truncated at 10000 characters]"
            return text
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
        return file_path.read_text(encoding="utf-8")
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
        return output or "(no output)"
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

            stmt = select(SemanticMemory).where(
                SemanticMemory.agent_id == str(agent.id),
            )
            if namespace:
                stmt = stmt.where(SemanticMemory.namespace == namespace)
            stmt = stmt.order_by(SemanticMemory.updated_at.desc()).limit(limit)
            result = await _session.execute(stmt)
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
    from nexus.gateway.outbound import hire_external_agent

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
