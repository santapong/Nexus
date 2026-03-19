"""SOPS-based secrets management for NEXUS.

Provides encrypted secret storage using Mozilla SOPS. Secrets are stored
in encrypted YAML/JSON files, decrypted at runtime. Supports AGE and
AWS KMS encryption backends.

Falls back gracefully to environment variables when SOPS is not configured,
allowing local development without SOPS setup.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

import structlog

from nexus.settings import settings

logger = structlog.get_logger()


class SOPSError(Exception):
    """Raised when SOPS operations fail."""


class SOPSClient:
    """Client for Mozilla SOPS encrypted secret management.

    Supports:
    - Decrypting SOPS-encrypted files (YAML/JSON)
    - Encrypting new secret files
    - Key rotation
    - Per-workspace secret scoping via file paths

    Args:
        secrets_dir: Directory containing encrypted secret files.
        age_key_file: Path to AGE private key for decryption.
        sops_binary: Path to the sops binary.
    """

    def __init__(
        self,
        secrets_dir: str = "",
        age_key_file: str = "",
        sops_binary: str = "sops",
    ) -> None:
        self.secrets_dir = Path(secrets_dir or settings.sops_secrets_dir)
        self.age_key_file = Path(age_key_file or settings.sops_age_key_file)
        self.sops_binary = sops_binary
        self._cache: dict[str, dict[str, Any]] = {}

    @property
    def is_configured(self) -> bool:
        """Check if SOPS is properly configured."""
        return bool(
            self.secrets_dir.exists()
            and self.age_key_file.exists()
        )

    async def decrypt_file(self, file_path: str | Path) -> dict[str, Any]:
        """Decrypt a SOPS-encrypted file and return its contents.

        Args:
            file_path: Path to the encrypted file (relative to secrets_dir or absolute).

        Returns:
            Decrypted contents as a dictionary.

        Raises:
            SOPSError: If decryption fails.
        """
        path = Path(file_path)
        if not path.is_absolute():
            path = self.secrets_dir / path

        if not path.exists():
            raise SOPSError(f"Encrypted file not found: {path}")

        cache_key = str(path)
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            env = {"SOPS_AGE_KEY_FILE": str(self.age_key_file)}
            result = await asyncio.to_thread(
                subprocess.run,
                [self.sops_binary, "--decrypt", str(path)],
                capture_output=True,
                text=True,
                timeout=30,
                env={**dict(__import__("os").environ), **env},
            )
            if result.returncode != 0:
                raise SOPSError(f"SOPS decrypt failed: {result.stderr}")

            data: dict[str, Any] = json.loads(result.stdout)
            self._cache[cache_key] = data
            logger.info("sops_file_decrypted", file=str(path))
            return data
        except json.JSONDecodeError as exc:
            raise SOPSError(f"Failed to parse decrypted content: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise SOPSError("SOPS decrypt timed out") from exc

    async def encrypt_file(
        self,
        data: dict[str, Any],
        file_path: str | Path,
        age_recipients: list[str] | None = None,
    ) -> None:
        """Encrypt data and write to a SOPS-encrypted file.

        Args:
            data: Data to encrypt.
            file_path: Output path for the encrypted file.
            age_recipients: AGE public keys for encryption. Uses default if not provided.

        Raises:
            SOPSError: If encryption fails.
        """
        path = Path(file_path)
        if not path.is_absolute():
            path = self.secrets_dir / path

        path.parent.mkdir(parents=True, exist_ok=True)

        # Write plaintext temporarily
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(data, indent=2))

        try:
            cmd = [self.sops_binary, "--encrypt"]
            if age_recipients:
                for recipient in age_recipients:
                    cmd.extend(["--age", recipient])
            cmd.extend(["--input-type", "json", "--output-type", "json"])
            cmd.append(str(temp_path))

            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                raise SOPSError(f"SOPS encrypt failed: {result.stderr}")

            # SOPS encrypts in-place, move to target
            if temp_path.exists():
                temp_path.rename(path)

            # Invalidate cache
            self._cache.pop(str(path), None)
            logger.info("sops_file_encrypted", file=str(path))
        except subprocess.TimeoutExpired as exc:
            raise SOPSError("SOPS encrypt timed out") from exc
        finally:
            if temp_path.exists():
                temp_path.unlink()

    async def get_secret(
        self,
        key: str,
        file_path: str = "secrets.json",
    ) -> str | None:
        """Get a single secret value from an encrypted file.

        Args:
            key: The secret key to retrieve.
            file_path: Encrypted file containing the secret.

        Returns:
            The secret value, or None if not found.
        """
        try:
            data = await self.decrypt_file(file_path)
            value = data.get(key)
            return str(value) if value is not None else None
        except SOPSError:
            logger.warning("sops_get_secret_fallback", key=key)
            return None

    async def get_workspace_secrets(
        self,
        workspace_id: str,
    ) -> dict[str, Any]:
        """Get all secrets for a specific workspace.

        Workspace secrets are stored in per-workspace files:
        {secrets_dir}/workspaces/{workspace_id}/secrets.json

        Args:
            workspace_id: The workspace identifier.

        Returns:
            Dictionary of secrets for the workspace.
        """
        file_path = f"workspaces/{workspace_id}/secrets.json"
        try:
            return await self.decrypt_file(file_path)
        except SOPSError:
            logger.info("sops_no_workspace_secrets", workspace_id=workspace_id)
            return {}

    async def rotate_keys(
        self,
        file_path: str | Path,
        new_age_recipients: list[str],
    ) -> None:
        """Rotate encryption keys for a SOPS file.

        Args:
            file_path: Path to the encrypted file.
            new_age_recipients: New AGE public keys.

        Raises:
            SOPSError: If key rotation fails.
        """
        path = Path(file_path)
        if not path.is_absolute():
            path = self.secrets_dir / path

        # Decrypt, re-encrypt with new keys
        data = await self.decrypt_file(path)
        self._cache.pop(str(path), None)
        await self.encrypt_file(data, path, age_recipients=new_age_recipients)
        logger.info("sops_keys_rotated", file=str(path))

    def clear_cache(self) -> None:
        """Clear the in-memory secret cache."""
        self._cache.clear()


class SecretManager:
    """Unified secret management that tries SOPS first, falls back to KeepSave/env.

    This is the main entry point for secret retrieval. It provides a consistent
    interface regardless of the underlying secret backend.
    """

    def __init__(self) -> None:
        self._sops = SOPSClient()
        self._env_cache: dict[str, str] = {}

    async def get_secret(
        self,
        key: str,
        *,
        workspace_id: str | None = None,
        task_id: str = "",
        trace_id: str = "",
    ) -> str | None:
        """Get a secret value using the configured backend.

        Resolution order:
        1. SOPS workspace-scoped file (if workspace_id provided and SOPS configured)
        2. SOPS global secrets file (if SOPS configured)
        3. KeepSave API (if configured)
        4. Environment variable (fallback)

        Args:
            key: The secret key to retrieve.
            workspace_id: Optional workspace scope.
            task_id: For audit logging.
            trace_id: For audit logging.

        Returns:
            The secret value, or None if not found.
        """
        # 1. SOPS workspace-scoped
        if workspace_id and self._sops.is_configured:
            value = await self._try_sops_workspace(key, workspace_id)
            if value is not None:
                logger.info(
                    "secret_resolved",
                    key=key,
                    source="sops_workspace",
                    task_id=task_id,
                    trace_id=trace_id,
                )
                return value

        # 2. SOPS global
        if self._sops.is_configured:
            value = await self._sops.get_secret(key)
            if value is not None:
                logger.info(
                    "secret_resolved",
                    key=key,
                    source="sops_global",
                    task_id=task_id,
                    trace_id=trace_id,
                )
                return value

        # 3. KeepSave (if configured)
        if settings.keepsave_url and settings.keepsave_api_key:
            value = await self._try_keepsave(key)
            if value is not None:
                logger.info(
                    "secret_resolved",
                    key=key,
                    source="keepsave",
                    task_id=task_id,
                    trace_id=trace_id,
                )
                return value

        # 4. Environment variable fallback
        import os

        value = os.environ.get(key) or os.environ.get(key.upper())
        if value is not None:
            logger.info(
                "secret_resolved",
                key=key,
                source="environment",
                task_id=task_id,
                trace_id=trace_id,
            )
        return value

    async def _try_sops_workspace(self, key: str, workspace_id: str) -> str | None:
        """Try to get a secret from workspace-scoped SOPS file."""
        try:
            secrets = await self._sops.get_workspace_secrets(workspace_id)
            value = secrets.get(key)
            return str(value) if value is not None else None
        except SOPSError:
            return None

    async def _try_keepsave(self, key: str) -> str | None:
        """Try to get a secret from KeepSave."""
        try:
            from nexus.integrations.keepsave.client import get_keepsave_client

            client = get_keepsave_client()
            result = await client.get_secret(key)
            if "error" not in result:
                value = result.get("value")
                return str(value) if value is not None else None
        except Exception as exc:
            logger.warning("keepsave_secret_fallback", key=key, error=str(exc))
        return None


# Singleton
_manager: SecretManager | None = None


def get_secret_manager() -> SecretManager:
    """Get or create the singleton SecretManager."""
    global _manager
    if _manager is None:
        _manager = SecretManager()
    return _manager
