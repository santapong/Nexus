"""MCP tool wrappers as standalone async functions for Phase 1.

Each function is a Pydantic AI tool — the docstring is used by the LLM
to understand when to call it. Keep docstrings clear and specific.

These implementations are standalone for Phase 1. They will be replaced
by the full MCP package adapter when that package is ready.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import httpx
import structlog

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
