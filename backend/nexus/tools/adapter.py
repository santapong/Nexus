"""MCP tool wrappers as standalone async functions for Phase 1-2.

Each function is a Pydantic AI tool - the docstring is used by the LLM
to understand when to call it. Keep docstrings clear and specific.

These implementations are standalone for Phase 1-2. They will be replaced
by the full MCP package adapter when that package is ready.

All tool executions are wrapped with OpenTelemetry trace spans when OTel is
configured. Traces are no-ops when OTel is disabled (zero overhead).

Security model
--------------
All irreversible tools (file_write, send_email, git_push, hire_external_agent)
MUST call ``require_approval()`` from ``nexus.tools.guards`` as the first line
of their function body. Approval is enforced HERE in the adapter — there is no
"guard chain" at the agent layer that does this automatically.

Irreversible tools obtain the per-call ``task_id``, ``agent_id``, and DB session
via the ``_tool_context`` ``ContextVar`` defined in this module. The agent
runtime (``nexus/agents/base.py``) is responsible for calling
``set_tool_context(...)`` before invoking the LLM for each task. If the
context is unset when an irreversible tool runs, the tool raises
``ToolContextUnsetError`` and refuses to execute.

All tool outputs are passed through ``sanitize_output()`` (PII detection +
redaction) AFTER size truncation. This is defense in depth — even if a tool
returns sensitive data, it is redacted before reaching the LLM context.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
import structlog
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.sanitization import sanitize_output
from nexus.db.models import EpisodicMemory, SemanticMemory
from nexus.integrations.otel.tracing import traced
from nexus.tools.guards import IrreversibleAction, require_approval

logger = structlog.get_logger()

_MAX_TOOL_OUTPUT_SIZE = 50_000  # 50KB max per tool response


# ─── Tool execution context ──────────────────────────────────────────────────
# Irreversible tools need task_id, agent_id, and a DB session to create
# HumanApproval records. Pydantic AI tools are plain functions called by the
# LLM runtime, so we use a ContextVar to thread per-task context into them.
# The agent runtime is responsible for setting this before invoking the LLM.


class ToolContextUnsetError(RuntimeError):
    """Raised when an irreversible tool runs without a tool execution context.

    This is a FAIL-LOUD safety mechanism. If the context isn't set, we cannot
    create a HumanApproval record, and the action MUST NOT proceed.
    """


class ToolNotConfigured(RuntimeError):  # noqa: N818 — public API name; renaming would break sandbox/client.py imports
    """Raised when a tool's integration is not configured in the environment.

    Examples:
      - send_email called but SMTP is not wired
      - sandbox tools called but E2B_API_KEY is missing
    """


@dataclass
class ToolExecutionContext:
    """Per-task context for tool execution.

    Attributes:
        task_id: The task this tool call belongs to.
        agent_id: The agent making the tool call.
        session_factory: Async DB session factory for creating sessions.
            We use a factory (not a session) because ``require_approval``
            polls for up to an hour — we don't want to hold a single session
            open that long.
    """

    task_id: str
    agent_id: str
    session_factory: Callable[..., Any]


_tool_context: ContextVar[ToolExecutionContext | None] = ContextVar(
    "nexus_tool_context",
    default=None,
)


def set_tool_context(
    *,
    task_id: str,
    agent_id: str,
    session_factory: Callable[..., Any],
) -> Any:
    """Set the per-task tool execution context.

    Called by the agent runtime (``nexus/agents/base.py``) before invoking the
    LLM. Returns a token that should be passed to ``reset_tool_context()`` in
    a ``finally`` block to restore the previous context.

    Args:
        task_id: The current task UUID.
        agent_id: The current agent UUID.
        session_factory: Callable returning an async session context manager.

    Returns:
        A token from ``ContextVar.set()`` for later reset.
    """
    return _tool_context.set(
        ToolExecutionContext(
            task_id=task_id,
            agent_id=agent_id,
            session_factory=session_factory,
        ),
    )


def reset_tool_context(token: Any) -> None:
    """Reset the tool execution context to its previous value.

    Args:
        token: The token returned by ``set_tool_context()``.
    """
    _tool_context.reset(token)


def _require_tool_context(tool_name: str) -> ToolExecutionContext:
    """Fetch the current tool execution context or fail loudly.

    Args:
        tool_name: Name of the calling tool (for error messages).

    Returns:
        The active ``ToolExecutionContext``.

    Raises:
        ToolContextUnsetError: If no context is set. Irreversible tools cannot
            proceed without this — there's no way to create the approval record.
    """
    ctx = _tool_context.get()
    if ctx is None:
        msg = (
            f"Irreversible tool {tool_name!r} was invoked without a tool "
            "execution context. The agent runtime must call "
            "nexus.tools.adapter.set_tool_context(...) before the LLM is "
            "given access to irreversible tools."
        )
        raise ToolContextUnsetError(msg)
    return ctx


async def _approve_or_raise(
    *,
    tool_name: str,
    description: str,
) -> ToolExecutionContext:
    """Call ``require_approval`` and commit the approval record.

    Centralizes the approval flow used by every irreversible tool.
    Opens a fresh DB session from the context's session factory, creates the
    HumanApproval record, and blocks until a human approves or rejects.

    Args:
        tool_name: The tool name (used as ``IrreversibleAction.action``).
        description: Human-readable summary of what will happen.

    Returns:
        The active ``ToolExecutionContext`` (so callers can reuse task_id).

    Raises:
        ToolContextUnsetError: If no tool context is set.
        ApprovalDeniedError: If the human rejected the action.
        ApprovalTimeoutError: If no response within the timeout.
    """
    ctx = _require_tool_context(tool_name)
    async with ctx.session_factory() as session:
        await require_approval(
            session=session,
            agent_id=ctx.agent_id,
            action=IrreversibleAction(
                action=tool_name,
                description=description,
                task_id=ctx.task_id,
            ),
        )
        await session.commit()
    return ctx


def _sanitize_tool_output(output: str) -> str:
    """Truncate then PII-sanitize tool output.

    Order matters: truncate first (cheap) so the PII scan runs over a bounded
    string. ``sanitize_output`` redacts API keys, tokens, emails, JWTs,
    private keys, etc. — defense in depth against tools leaking secrets back
    into the LLM context window.
    """
    if len(output) > _MAX_TOOL_OUTPUT_SIZE:
        output = output[:_MAX_TOOL_OUTPUT_SIZE] + "\n\n[OUTPUT TRUNCATED — exceeded 50KB limit]"

    ctx = _tool_context.get()
    task_id = ctx.task_id if ctx is not None else ""
    agent_id = ctx.agent_id if ctx is not None else ""
    sanitized = sanitize_output(output, task_id=task_id, agent_id=agent_id)
    # ``sanitize_output`` preserves string inputs as strings.
    return sanitized if isinstance(sanitized, str) else str(sanitized)


# ─── READ-ONLY tools (no approval needed) ────────────────────────────────────


@traced("tool.web_search")
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
        return _sanitize_tool_output(f"Search failed: {exc}")


@traced("tool.web_fetch")
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
                import re
                from html.parser import HTMLParser

                class _TextExtractor(HTMLParser):
                    """Extract visible text from HTML, skipping script/style."""

                    def __init__(self) -> None:
                        super().__init__()
                        self._parts: list[str] = []
                        self._skip_depth = 0

                    def handle_starttag(
                        self,
                        tag: str,
                        attrs: list[tuple[str, str | None]],
                    ) -> None:
                        if tag.lower() in ("script", "style"):
                            self._skip_depth += 1

                    def handle_endtag(self, tag: str) -> None:
                        if tag.lower() in ("script", "style") and self._skip_depth > 0:
                            self._skip_depth -= 1

                    def handle_data(self, data: str) -> None:
                        if self._skip_depth == 0:
                            self._parts.append(data)

                    def get_text(self) -> str:
                        return re.sub(r"\s+", " ", " ".join(self._parts)).strip()

                parser = _TextExtractor()
                parser.feed(response.text)
                text = parser.get_text()
            else:
                text = response.text

            if len(text) > 10_000:
                text = text[:10_000] + "\n\n[Content truncated at 10000 characters]"
            return _sanitize_tool_output(text)
    except Exception as exc:
        logger.error("web_fetch_failed", url=url, error=str(exc))
        return _sanitize_tool_output(f"Fetch failed: {exc}")


@traced("tool.file_read")
async def tool_file_read(path: str) -> str:
    """Read the contents of a file.

    Args:
        path: Absolute or relative path to the file.

    Returns:
        File contents as string, or an error message if file not found.
    """
    from nexus.settings import settings

    file_path = Path(path).resolve()

    # Path traversal prevention — restrict to allowed directories
    if settings.tool_allowed_dirs:
        allowed = [
            Path(d.strip()).resolve() for d in settings.tool_allowed_dirs.split(",") if d.strip()
        ]
        if allowed and not any(file_path == a or file_path.is_relative_to(a) for a in allowed):
            logger.warning(
                "file_read_denied",
                path=str(file_path),
                allowed_dirs=settings.tool_allowed_dirs,
            )
            return _sanitize_tool_output(
                f"Error: Access denied — file outside allowed directories: {path}",
            )

    if not file_path.exists():
        return _sanitize_tool_output(f"Error: File not found: {path}")
    if not file_path.is_file():
        return _sanitize_tool_output(f"Error: Not a file: {path}")

    # File size check
    try:
        file_size = file_path.stat().st_size
        if file_size > settings.tool_file_read_max_bytes:
            return _sanitize_tool_output(
                f"Error: File too large ({file_size:,} bytes, "
                f"max {settings.tool_file_read_max_bytes:,} bytes): {path}",
            )
    except OSError as exc:
        return _sanitize_tool_output(f"Error checking file size: {exc}")

    try:
        return _sanitize_tool_output(file_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _sanitize_tool_output(f"Error reading file: {exc}")


@traced("tool.code_execute")
async def tool_code_execute(code: str, language: str = "python") -> str:
    """Execute code in a sandboxed subprocess with a 30-second timeout.

    Resource limits: 256MB memory, 30s wall clock timeout.
    Note: Full network isolation requires Docker/nsjail sandbox (see §8).

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
        return _sanitize_tool_output(
            f"Unsupported language: {language}. Use 'python' or 'bash'.",
        )

    logger.info(
        "code_execute_start",
        language=language,
        code_length=len(code),
        code_preview=code[:200],
    )

    try:
        import resource

        def _set_resource_limits() -> None:
            """Set memory and CPU limits for the child process."""
            # 256MB memory limit
            resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
            # 30s CPU time limit
            resource.setrlimit(resource.RLIMIT_CPU, (30, 30))

        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            preexec_fn=_set_resource_limits,
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        return _sanitize_tool_output(output or "(no output)")
    except subprocess.TimeoutExpired:
        return _sanitize_tool_output("Error: Code execution timed out (30s limit)")
    except Exception as exc:
        return _sanitize_tool_output(f"Error executing code: {exc}")


@traced("tool.memory_read")
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
        return _sanitize_tool_output(
            "Error: No database session available for memory_read.",
        )

    try:
        if memory_type == "episodic":
            from nexus.db.models import Agent

            # Find agent by role
            agent_stmt = select(Agent).where(Agent.role == agent_role)
            agent_result = await _session.execute(agent_stmt)
            agent = agent_result.scalar_one_or_none()
            if not agent:
                return _sanitize_tool_output(
                    f"Error: No agent found with role '{agent_role}'",
                )

            stmt = (
                select(EpisodicMemory)
                .where(EpisodicMemory.agent_id == str(agent.id))
                .order_by(EpisodicMemory.created_at.desc())
                .limit(limit)
            )
            result = await _session.execute(stmt)
            episodes = result.scalars().all()

            if not episodes:
                return _sanitize_tool_output(
                    f"No episodic memories found for {agent_role} agent.",
                )

            lines = [f"Episodic memories for {agent_role} (last {limit}):"]
            for ep in episodes:
                lines.append(
                    f"- [{ep.outcome}] {ep.summary[:200]} "
                    f"(tokens: {ep.tokens_used}, duration: {ep.duration_seconds}s)"
                )
            return _sanitize_tool_output("\n".join(lines))

        elif memory_type == "semantic":
            from nexus.db.models import Agent

            agent_stmt = select(Agent).where(Agent.role == agent_role)
            agent_result = await _session.execute(agent_stmt)
            agent = agent_result.scalar_one_or_none()
            if not agent:
                return _sanitize_tool_output(
                    f"Error: No agent found with role '{agent_role}'",
                )

            sem_stmt = select(SemanticMemory).where(
                SemanticMemory.agent_id == str(agent.id),
            )
            if namespace:
                sem_stmt = sem_stmt.where(SemanticMemory.namespace == namespace)
            sem_stmt = sem_stmt.order_by(SemanticMemory.updated_at.desc()).limit(limit)
            result = await _session.execute(sem_stmt)
            facts = result.scalars().all()

            if not facts:
                return _sanitize_tool_output(
                    f"No semantic memories found for {agent_role} agent.",
                )

            lines = [f"Semantic memories for {agent_role}:"]
            for fact in facts:
                lines.append(
                    f"- [{fact.namespace}] {fact.key}: {fact.value[:200]} "
                    f"(confidence: {fact.confidence})"
                )
            return _sanitize_tool_output("\n".join(lines))

        else:
            return _sanitize_tool_output(
                f"Error: Unknown memory_type '{memory_type}'. Use 'episodic' or 'semantic'.",
            )
    except Exception as exc:
        logger.error("memory_read_failed", agent_role=agent_role, error=str(exc))
        return _sanitize_tool_output(f"Memory read failed: {exc}")


# ─── LLM-POWERED planning & design tools ─────────────────────────────────────


@traced("tool.create_plan")
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


@traced("tool.design_system")
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


@traced("tool.design_database")
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


@traced("tool.design_api")
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
# Each irreversible tool calls ``_approve_or_raise(...)`` as its FIRST line.
# The approval blocks until a human approves or rejects via the dashboard.


@traced("tool.file_write")
async def tool_file_write(path: str, content: str) -> str:
    """Write content to a file. This action requires human approval.

    Args:
        path: File path to write to.
        content: Content to write.

    Returns:
        Confirmation message with bytes written.
    """
    await _approve_or_raise(
        tool_name="file_write",
        description=f"Write {len(content)} chars to {path}",
    )

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    logger.info("file_written", path=path, size=len(content))
    return _sanitize_tool_output(f"Written {len(content)} chars to {path}")


@traced("tool.send_email")
async def tool_send_email(to: str, subject: str, body: str) -> str:
    """Send an email. This action requires human approval and cannot be undone.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body text.

    Returns:
        Confirmation message with recipient and subject.

    Raises:
        ToolNotConfigured: SMTP integration is not wired. Set the SMTP_* env
            vars and implement ``nexus.integrations.smtp`` before using this.
    """
    await _approve_or_raise(
        tool_name="send_email",
        description=f"Send email to {to}: {subject}",
    )

    # The actual SMTP integration is not yet wired. Failing loudly is much
    # safer than returning a fake confirmation — agents would otherwise
    # believe the email was delivered when in fact nothing was sent.
    logger.error(
        "send_email_not_configured",
        to=to,
        subject=subject,
        body_length=len(body),
    )
    raise ToolNotConfigured(
        "send_email integration is not wired — set SMTP_* env vars and "
        "implement nexus.integrations.smtp",
    )


# Patterns for files that must never be committed via tool_git_push.
# Matching is case-insensitive where appropriate; we test each staged path
# against every pattern before allowing the commit to proceed.
_GIT_PUSH_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\.env(\..+)?$"),
    re.compile(r"(?i)key"),
    re.compile(r"(?i)secret"),
    re.compile(r"(?i)token"),
    re.compile(r"\.pem$"),
    re.compile(r"id_rsa"),
    re.compile(r"\.p12$"),
]


def _scan_staged_files_for_secrets(repo_path: str) -> list[str]:
    """Return list of staged file paths that match secret-leak patterns.

    Runs ``git diff --cached --name-only`` (no network, no side effects) to
    enumerate what would be committed, then checks each filename against the
    forbidden-pattern list.

    Args:
        repo_path: Path to the git repository.

    Returns:
        List of offending file paths (empty list if all-clear).
    """
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=repo_path,
        check=False,
    )
    if result.returncode != 0:
        # Non-zero from git here means we couldn't inspect the index. Refuse
        # the push rather than silently committing.
        raise RuntimeError(
            f"git diff --cached failed (rc={result.returncode}): {result.stderr.strip()}",
        )

    staged = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    offenders: list[str] = []
    for path in staged:
        for pattern in _GIT_PUSH_SECRET_PATTERNS:
            if pattern.search(path):
                offenders.append(path)
                break
    return offenders


@traced("tool.git_push")
async def tool_git_push(repo_path: str, branch: str, message: str) -> str:
    """Push code changes to a git repository. This action requires human approval.

    Args:
        repo_path: Path to the git repository.
        branch: Branch name to push to.
        message: Commit message for the changes.

    Returns:
        Git push result or error message.
    """
    await _approve_or_raise(
        tool_name="git_push",
        description=f"git push {branch} from {repo_path}: {message}",
    )

    try:
        # Stage all changes first so the secret-leak scan can see what's
        # about to be committed.
        add_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "add", "-A"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=repo_path,
            check=False,
        )
        if add_result.returncode != 0:
            return _sanitize_tool_output(
                f"git add failed: {add_result.stderr.strip()}",
            )

        # Pre-flight: refuse to commit files whose names look like secrets.
        # This is a guard against the LLM accidentally adding .env, *.pem,
        # id_rsa, or anything matching key/secret/token in its name.
        try:
            offenders = await asyncio.to_thread(_scan_staged_files_for_secrets, repo_path)
        except RuntimeError as exc:
            # Reset the index before bailing so we don't leave the repo
            # in a half-staged state.
            await asyncio.to_thread(
                subprocess.run,
                ["git", "reset", "HEAD"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=repo_path,
                check=False,
            )
            logger.error(
                "git_push_preflight_failed",
                repo=repo_path,
                error=str(exc),
            )
            raise RuntimeError(f"git_push pre-flight scan failed: {exc}") from exc

        if offenders:
            # Reset the staged changes so a follow-up call doesn't quietly
            # inherit the dangerous staging area.
            await asyncio.to_thread(
                subprocess.run,
                ["git", "reset", "HEAD"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=repo_path,
                check=False,
            )
            logger.error(
                "git_push_blocked_secret_leak",
                repo=repo_path,
                branch=branch,
                offenders=offenders,
            )
            raise RuntimeError(
                "git_push refused: staged files match secret-leak patterns "
                f"(.env / key / secret / token / .pem / id_rsa / .p12): "
                f"{offenders}",
            )

        # Commit
        commit_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "commit", "-m", message],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=repo_path,
            check=False,
        )
        if commit_result.returncode != 0:
            err = commit_result.stderr.strip() or commit_result.stdout.strip()
            return _sanitize_tool_output(f"git commit failed: {err}")

        # Push
        push_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "push", "origin", branch],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=repo_path,
            check=False,
        )

        output = push_result.stdout
        if push_result.stderr:
            output += f"\n{push_result.stderr}"
        if push_result.returncode != 0:
            return _sanitize_tool_output(f"Git push failed: {output}")

        logger.info("git_pushed", repo=repo_path, branch=branch)
        return _sanitize_tool_output(f"Pushed to {branch}: {message}\n{output}")
    except subprocess.TimeoutExpired:
        return _sanitize_tool_output("Error: Git operation timed out")


# ─── External agent response validation ──────────────────────────────────────


class HiredAgentResponse(BaseModel):
    """Strict schema for what we accept back from an external A2A agent.

    Used to defend the calling agent's context window from prompt-injection
    attacks delivered via ``result.output`` from an untrusted external party.
    """

    status: Literal["success", "failure"]
    output: str = Field(default="", max_length=10_000)
    error: str | None = Field(default=None, max_length=2_000)


def _coerce_hired_agent_response(result: Any) -> HiredAgentResponse:
    """Coerce a raw outbound A2A result into the strict response schema.

    The outbound helper returns an ``ExternalAgentResult`` with an arbitrary
    ``output: dict | None`` and a free-form ``status: str``. We squeeze that
    into our hardened ``HiredAgentResponse`` model so any extra fields are
    discarded and the ``output`` is bounded.

    Args:
        result: An ``ExternalAgentResult`` (or anything with ``status``,
            ``output``, ``error`` attributes).

    Returns:
        A validated ``HiredAgentResponse``.
    """
    raw_status = str(getattr(result, "status", "")).lower()
    status: Literal["success", "failure"] = (
        "success" if raw_status in {"success", "completed", "ok", "done"} else "failure"
    )

    raw_output = getattr(result, "output", None)
    if raw_output is None:
        output_text = ""
    elif isinstance(raw_output, dict):
        # Prefer the conventional "result" key, fall back to the whole dict.
        output_text = str(raw_output.get("result", raw_output))
    else:
        output_text = str(raw_output)

    # Hard length cap before pydantic validation; defensive belt-and-braces.
    if len(output_text) > 10_000:
        output_text = output_text[:10_000]

    error_text = getattr(result, "error", None)
    if error_text is not None:
        error_text = str(error_text)
        if len(error_text) > 2_000:
            error_text = error_text[:2_000]

    return HiredAgentResponse(
        status=status,
        output=output_text,
        error=error_text,
    )


@traced("tool.hire_external_agent")
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
    await _approve_or_raise(
        tool_name="hire_external_agent",
        description=f"Hire external agent at {agent_url} (skill={skill_id}): {instruction[:200]}",
    )

    from nexus.integrations.a2a.outbound import hire_external_agent

    try:
        raw_result = await hire_external_agent(
            agent_url=agent_url,
            instruction=instruction,
            skill_id=skill_id,
            bearer_token=bearer_token,
        )
    except Exception as exc:
        logger.error(
            "hire_external_agent_failed",
            agent_url=agent_url,
            error=str(exc),
        )
        return _sanitize_tool_output(f"Failed to hire external agent: {exc}")

    # Validate the external response against our hardened schema. This is the
    # prompt-injection boundary — anything from outside NEXUS must be
    # length-capped, typed, and PII-sanitized before it touches the LLM.
    try:
        validated = _coerce_hired_agent_response(raw_result)
    except ValidationError as exc:
        logger.error(
            "hire_external_agent_invalid_response",
            agent_url=agent_url,
            errors=exc.errors(),
        )
        return _sanitize_tool_output(
            "External agent returned a response that failed schema validation; "
            "result discarded for safety.",
        )

    if validated.error:
        return _sanitize_tool_output(
            f"External agent error: {validated.error}",
        )
    if validated.output:
        return _sanitize_tool_output(
            f"External agent result ({validated.status}):\n{validated.output}",
        )
    return _sanitize_tool_output(
        f"External agent completed with status: {validated.status}",
    )


@traced("tool.analyze_image")
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
        return _sanitize_tool_output(f"Error: Image not found: {image_path}")

    mime_type, _ = mimetypes.guess_type(image_path)
    supported = {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "application/pdf",
    }
    if mime_type not in supported:
        return _sanitize_tool_output(
            f"Error: Unsupported file type '{mime_type}'. Supported: {', '.join(supported)}",
        )

    # Read and encode the image
    try:
        image_data = file_path.read_bytes()
        if len(image_data) > 20 * 1024 * 1024:  # 20MB limit
            return _sanitize_tool_output("Error: Image file exceeds 20MB size limit")
        b64_data = base64.b64encode(image_data).decode("utf-8")
    except Exception as exc:
        return _sanitize_tool_output(f"Error reading image: {exc}")

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
                return _sanitize_tool_output("No response from Gemini vision model.")

        else:
            return _sanitize_tool_output(
                "Error: No vision-capable LLM API key configured "
                "(need ANTHROPIC_API_KEY or GOOGLE_API_KEY)",
            )

    except Exception as exc:
        logger.error("analyze_image_failed", image_path=image_path, error=str(exc))
        return _sanitize_tool_output(f"Image analysis failed: {exc}")


# ─── SANDBOX tools (E2B Firecracker microVM isolation) ────────────────────────


@traced("tool.sandbox_execute")
async def tool_sandbox_execute(code: str, language: str = "python") -> str:
    """Execute code in an isolated Firecracker microVM sandbox.

    The sandbox provides hardware-level isolation (same technology as AWS Lambda).
    Each execution creates a fresh environment — no state persists between calls.
    Supports Python, Bash, Node.js, and other languages.

    Args:
        code: The code to execute.
        language: Programming language (python, bash, node). Defaults to python.

    Returns:
        The execution output (stdout + stderr).
    """
    from nexus.tools.sandbox.client import execute_code

    result = await execute_code(code=code, language=language)
    output = result.output
    if not result.success:
        output = f"[Exit code: {result.exit_code}]\n{output}"
    return _sanitize_tool_output(output)


@traced("tool.sandbox_project")
async def tool_sandbox_project(repo_url: str, commands: str) -> str:
    """Clone a git repository into an isolated sandbox and run commands.

    Creates a Firecracker microVM, clones the repository, and executes
    the specified commands sequentially. Useful for running test suites,
    building projects, or verifying code changes.

    This action requires human approval as it involves network access
    and compute costs.

    Args:
        repo_url: Git repository URL to clone (e.g. https://github.com/user/repo).
        commands: Semicolon-separated commands to run
            (e.g. "pip install -r requirements.txt;pytest").

    Returns:
        Combined output from all commands.
    """
    from nexus.tools.sandbox.client import execute_project

    cmd_list = [cmd.strip() for cmd in commands.split(";") if cmd.strip()]
    if not cmd_list:
        return _sanitize_tool_output(
            "Error: No commands provided. Separate commands with semicolons.",
        )

    result = await execute_project(repo_url=repo_url, commands=cmd_list)
    output = result.output
    if not result.success:
        output = f"[Failed at exit code: {result.exit_code}]\n{output}"
    output += f"\n\n[Duration: {result.duration_seconds:.1f}s]"
    return _sanitize_tool_output(output)
