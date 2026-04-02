"""Git operations for workspace storage.

All git commands run via subprocess wrapped in asyncio.to_thread to avoid
blocking the event loop. Repos are bare git repositories on a persistent
Docker volume at the configured workspace_repos_base_path.

Path convention: {base_path}/{workspace_id}/{project_slug}.git
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
import shutil
import subprocess
import tempfile

import structlog

from nexus.settings import settings

logger = structlog.get_logger()


def _run_git(
    *args: str,
    cwd: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a git command synchronously. Must be called via asyncio.to_thread."""
    cmd = ["git", *args]
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
        timeout=60,
    )


def _bare_repo_path(workspace_id: str, project_slug: str) -> str:
    """Return the absolute path to a bare git repo."""
    return os.path.join(
        settings.workspace_repos_base_path,
        workspace_id,
        f"{project_slug}.git",
    )


async def init_repo(workspace_id: str, project_slug: str) -> str:
    """Initialize a bare git repository for a workspace project.

    Args:
        workspace_id: The workspace UUID.
        project_slug: URL-friendly project identifier.

    Returns:
        Absolute path to the bare repo.
    """
    repo_path = _bare_repo_path(workspace_id, project_slug)

    def _init() -> str:
        os.makedirs(repo_path, exist_ok=True)
        _run_git("init", "--bare", "--initial-branch=main", repo_path)
        logger.info(
            "workspace_repo_initialized",
            workspace_id=workspace_id,
            project_slug=project_slug,
            repo_path=repo_path,
        )
        return repo_path

    return await asyncio.to_thread(_init)


async def write_file(
    workspace_id: str,
    project_slug: str,
    file_path: str,
    content: str | bytes,
    commit_message: str,
    author_name: str = "nexus-agent",
    author_email: str = "agent@nexus.local",
) -> str:
    """Write a file to the workspace git repo and commit.

    Clones the bare repo to a temp dir, writes the file, commits,
    and pushes back to the bare repo.

    Args:
        workspace_id: The workspace UUID.
        project_slug: Project identifier.
        file_path: Relative file path within the project.
        content: File content (str for text, bytes for binary).
        commit_message: Git commit message.
        author_name: Git author name.
        author_email: Git author email.

    Returns:
        The commit SHA of the new commit.
    """
    bare_path = _bare_repo_path(workspace_id, project_slug)

    def _write() -> str:
        with tempfile.TemporaryDirectory(prefix="nexus-ws-") as tmp_dir:
            # Clone the bare repo (or init if empty)
            try:
                _run_git("clone", bare_path, tmp_dir)
            except subprocess.CalledProcessError:
                # Bare repo might be empty — init working dir and set remote
                _run_git("init", "--initial-branch=main", tmp_dir)
                _run_git("remote", "add", "origin", bare_path, cwd=tmp_dir)

            # Write the file
            full_path = os.path.join(tmp_dir, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            if isinstance(content, bytes):
                with open(full_path, "wb") as f:
                    f.write(content)
            else:
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)

            # Configure git user for this repo
            _run_git("config", "user.name", author_name, cwd=tmp_dir)
            _run_git("config", "user.email", author_email, cwd=tmp_dir)

            # Stage and commit
            _run_git("add", file_path, cwd=tmp_dir)
            _run_git("commit", "-m", commit_message, cwd=tmp_dir)

            # Get the commit SHA
            result = _run_git("rev-parse", "HEAD", cwd=tmp_dir)
            commit_sha = result.stdout.strip()

            # Push to bare repo
            _run_git("push", "origin", "main", cwd=tmp_dir)

            return commit_sha

    return await asyncio.to_thread(_write)


async def read_file(
    workspace_id: str,
    project_slug: str,
    file_path: str,
    commit_sha: str | None = None,
) -> str | None:
    """Read a file from the workspace git repo.

    Args:
        workspace_id: The workspace UUID.
        project_slug: Project identifier.
        file_path: Relative file path within the project.
        commit_sha: Optional specific commit to read from. Defaults to HEAD.

    Returns:
        File content as string, or None if file not found.
    """
    bare_path = _bare_repo_path(workspace_id, project_slug)
    ref = commit_sha or "HEAD"

    def _read() -> str | None:
        try:
            result = _run_git("show", f"{ref}:{file_path}", cwd=bare_path)
            return result.stdout
        except subprocess.CalledProcessError:
            return None

    return await asyncio.to_thread(_read)


async def list_files(
    workspace_id: str,
    project_slug: str,
    path_prefix: str = "",
) -> list[str]:
    """List files in the workspace git repo.

    Args:
        workspace_id: The workspace UUID.
        project_slug: Project identifier.
        path_prefix: Optional prefix to filter files.

    Returns:
        List of file paths relative to repo root.
    """
    bare_path = _bare_repo_path(workspace_id, project_slug)

    def _list() -> list[str]:
        try:
            result = _run_git("ls-tree", "-r", "--name-only", "HEAD", cwd=bare_path)
            files = [f for f in result.stdout.strip().split("\n") if f]
            if path_prefix:
                files = [f for f in files if f.startswith(path_prefix)]
            return files
        except subprocess.CalledProcessError:
            return []

    return await asyncio.to_thread(_list)


async def get_file_history(
    workspace_id: str,
    project_slug: str,
    file_path: str,
    max_entries: int = 20,
) -> list[dict[str, str]]:
    """Get git log for a specific file.

    Args:
        workspace_id: The workspace UUID.
        project_slug: Project identifier.
        file_path: Relative file path.
        max_entries: Maximum number of log entries.

    Returns:
        List of dicts with commit_sha, message, author, date.
    """
    bare_path = _bare_repo_path(workspace_id, project_slug)

    def _history() -> list[dict[str, str]]:
        try:
            result = _run_git(
                "log",
                f"-{max_entries}",
                "--format=%H|%s|%an|%aI",
                "--",
                file_path,
                cwd=bare_path,
            )
            entries = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|", 3)
                if len(parts) == 4:
                    entries.append(
                        {
                            "commit_sha": parts[0],
                            "message": parts[1],
                            "author": parts[2],
                            "date": parts[3],
                        }
                    )
            return entries
        except subprocess.CalledProcessError:
            return []

    return await asyncio.to_thread(_history)


async def delete_repo(workspace_id: str, project_slug: str) -> None:
    """Delete a bare git repository. Use with caution.

    Args:
        workspace_id: The workspace UUID.
        project_slug: Project identifier.
    """
    repo_path = _bare_repo_path(workspace_id, project_slug)

    def _delete() -> None:
        if os.path.exists(repo_path):
            shutil.rmtree(repo_path)
            logger.info(
                "workspace_repo_deleted",
                workspace_id=workspace_id,
                project_slug=project_slug,
            )

    await asyncio.to_thread(_delete)


def guess_mime_type(file_path: str) -> str | None:
    """Guess MIME type from file extension."""
    mime, _ = mimetypes.guess_type(file_path)
    return mime


def is_binary_file(file_path: str) -> bool:
    """Check if a file is likely binary based on MIME type."""
    mime = guess_mime_type(file_path)
    if mime is None:
        return False
    return not mime.startswith("text/") and mime not in (
        "application/json",
        "application/xml",
        "application/javascript",
        "application/typescript",
        "application/x-yaml",
        "application/toml",
    )
