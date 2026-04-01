"""E2B sandbox client wrapper for NEXUS agent code execution.

Provides isolated Firecracker microVM environments for agents to:
- Execute code snippets safely
- Clone and test repositories
- Install dependencies and build projects

Each sandbox is ephemeral — created per task, destroyed after completion.
Uses E2B's Python SDK with session management and cost tracking.

Gracefully degrades when E2B is not configured (returns error message).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog

from nexus.settings import settings

logger = structlog.get_logger()


@dataclass
class SandboxResult:
    """Result from a sandbox execution."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_seconds: float = 0.0
    error: str | None = None

    @property
    def output(self) -> str:
        """Combined stdout + stderr output."""
        parts: list[str] = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(f"[STDERR]\n{self.stderr}")
        if self.error:
            parts.append(f"[ERROR]\n{self.error}")
        return "\n".join(parts) if parts else "(no output)"

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and self.error is None


@dataclass
class SandboxSession:
    """Tracks an active sandbox session for cost accounting."""

    sandbox_id: str = ""
    start_time: float = field(default_factory=time.monotonic)
    commands_run: int = 0

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.start_time


def _check_configured() -> bool:
    """Check if E2B is configured."""
    return bool(settings.e2b_api_key)


async def execute_code(
    code: str,
    language: str = "python",
    timeout_seconds: int = 60,
    task_id: str = "",
) -> SandboxResult:
    """Execute a code snippet in an isolated E2B sandbox.

    Creates an ephemeral Firecracker microVM, runs the code, and
    destroys the sandbox. Hardware-level isolation (same as AWS Lambda).

    Args:
        code: Code to execute.
        language: Programming language (python, bash, node, etc.).
        timeout_seconds: Max execution time.
        task_id: Associated task for cost tracking.

    Returns:
        SandboxResult with stdout, stderr, and exit code.
    """
    if not _check_configured():
        return SandboxResult(
            error="E2B sandbox not configured. Set E2B_API_KEY in environment.",
            exit_code=1,
        )

    start = time.monotonic()

    try:
        from e2b_code_interpreter import Sandbox

        sandbox = Sandbox(api_key=settings.e2b_api_key, timeout=timeout_seconds)
        session = SandboxSession(sandbox_id=sandbox.sandbox_id)

        try:
            if language == "python":
                execution = sandbox.run_code(code)
                stdout = "\n".join(str(r.text) for r in execution.results if r.text) if execution.results else ""
                stderr = "\n".join(execution.logs.stderr) if execution.logs.stderr else ""
                stdout_logs = "\n".join(execution.logs.stdout) if execution.logs.stdout else ""
                if stdout_logs and not stdout:
                    stdout = stdout_logs
                return SandboxResult(
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=0 if execution.error is None else 1,
                    duration_seconds=time.monotonic() - start,
                    error=str(execution.error) if execution.error else None,
                )
            else:
                # For non-Python: use shell execution
                result = sandbox.commands.run(code, timeout=timeout_seconds)
                return SandboxResult(
                    stdout=result.stdout,
                    stderr=result.stderr,
                    exit_code=result.exit_code,
                    duration_seconds=time.monotonic() - start,
                )
        finally:
            sandbox.kill()
            logger.info(
                "sandbox_destroyed",
                sandbox_id=session.sandbox_id,
                duration_seconds=round(session.elapsed_seconds, 2),
                task_id=task_id,
            )

    except ImportError:
        return SandboxResult(
            error="E2B SDK not installed. Run: pip install e2b-code-interpreter",
            exit_code=1,
        )
    except Exception as exc:
        logger.error("sandbox_execution_failed", error=str(exc), task_id=task_id)
        return SandboxResult(
            error=f"Sandbox execution failed: {exc}",
            exit_code=1,
            duration_seconds=time.monotonic() - start,
        )


async def execute_project(
    repo_url: str,
    commands: list[str],
    timeout_seconds: int = 300,
    task_id: str = "",
) -> SandboxResult:
    """Clone a repository and execute commands in an isolated sandbox.

    Creates a Firecracker microVM, clones the repo, and runs each
    command sequentially. The sandbox has network access for git clone
    and package installation.

    Args:
        repo_url: Git repository URL to clone.
        commands: List of shell commands to execute sequentially.
        timeout_seconds: Max total execution time.
        task_id: Associated task for cost tracking.

    Returns:
        SandboxResult with combined output from all commands.
    """
    if not _check_configured():
        return SandboxResult(
            error="E2B sandbox not configured. Set E2B_API_KEY in environment.",
            exit_code=1,
        )

    start = time.monotonic()

    try:
        from e2b_code_interpreter import Sandbox

        sandbox = Sandbox(api_key=settings.e2b_api_key, timeout=timeout_seconds)
        session = SandboxSession(sandbox_id=sandbox.sandbox_id)

        try:
            all_stdout: list[str] = []
            all_stderr: list[str] = []

            # Clone the repository
            clone_result = sandbox.commands.run(
                f"git clone {repo_url} /workspace",
                timeout=120,
            )
            all_stdout.append(f"[git clone]\n{clone_result.stdout}")
            if clone_result.exit_code != 0:
                return SandboxResult(
                    stdout="\n".join(all_stdout),
                    stderr=clone_result.stderr,
                    exit_code=clone_result.exit_code,
                    duration_seconds=time.monotonic() - start,
                    error=f"Git clone failed: {clone_result.stderr}",
                )

            # Execute each command
            for i, cmd in enumerate(commands):
                session.commands_run += 1
                cmd_result = sandbox.commands.run(
                    f"cd /workspace && {cmd}",
                    timeout=timeout_seconds,
                )
                all_stdout.append(f"[{cmd}]\n{cmd_result.stdout}")
                if cmd_result.stderr:
                    all_stderr.append(f"[{cmd}]\n{cmd_result.stderr}")

                if cmd_result.exit_code != 0:
                    return SandboxResult(
                        stdout="\n".join(all_stdout),
                        stderr="\n".join(all_stderr),
                        exit_code=cmd_result.exit_code,
                        duration_seconds=time.monotonic() - start,
                        error=f"Command failed at step {i + 1}/{len(commands)}: {cmd}",
                    )

            return SandboxResult(
                stdout="\n".join(all_stdout),
                stderr="\n".join(all_stderr),
                exit_code=0,
                duration_seconds=time.monotonic() - start,
            )

        finally:
            sandbox.kill()
            logger.info(
                "sandbox_project_destroyed",
                sandbox_id=session.sandbox_id,
                duration_seconds=round(session.elapsed_seconds, 2),
                commands_run=session.commands_run,
                task_id=task_id,
            )

    except ImportError:
        return SandboxResult(
            error="E2B SDK not installed. Run: pip install e2b-code-interpreter",
            exit_code=1,
        )
    except Exception as exc:
        logger.error("sandbox_project_failed", error=str(exc), task_id=task_id)
        return SandboxResult(
            error=f"Sandbox project execution failed: {exc}",
            exit_code=1,
            duration_seconds=time.monotonic() - start,
        )
