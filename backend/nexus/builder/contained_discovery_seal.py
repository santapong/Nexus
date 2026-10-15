"""Process-only receipt minted by the concrete fixed discovery path, not a portable DTO."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from nexus.builder.contained_evidence_types import ExactContainer

if TYPE_CHECKING:
    from nexus.builder.contained_process_contracts import ProcessRunBinding

_ISSUER = object()


class FixedDiscoverySeal:
    __slots__ = ("_binding_sha", "_container", "_issuer", "_runtime_pid", "reply_sha256")

    def __init__(
        self,
        issuer: object,
        container: ExactContainer,
        binding: ProcessRunBinding,
        runtime_pid: int,
        raw: bytes,
    ) -> None:
        if issuer is not _ISSUER:
            raise TypeError("Fixed discovery seals cannot be deserialized or caller constructed")
        self._issuer, self._container, self._runtime_pid = issuer, container, runtime_pid
        self._binding_sha = hashlib.sha256(binding.model_dump_json().encode()).hexdigest()
        self.reply_sha256 = hashlib.sha256(raw).hexdigest()

    @property
    def container(self) -> ExactContainer:
        return self._container

    def require(
        self, binding: ProcessRunBinding, runtime_pid: int, container: ExactContainer
    ) -> None:
        if (
            type(self) is not FixedDiscoverySeal
            or self._issuer is not _ISSUER
            or container is not self._container
            or runtime_pid != self._runtime_pid
            or self._binding_sha != hashlib.sha256(binding.model_dump_json().encode()).hexdigest()
            or (
                container.company_id,
                container.action_id,
                container.image_id,
                container.container_name,
                container.runtime_pid,
            )
            != (
                binding.company_id,
                binding.action_id,
                binding.image_id,
                binding.container_name,
                runtime_pid,
            )
        ):
            raise ValueError("Fixed discovery seal belongs to another owned spawn or object")


def _mint_fixed_discovery(
    container: ExactContainer,
    binding: ProcessRunBinding,
    runtime_pid: int,
    raw: bytes,
) -> FixedDiscoverySeal:
    """Called only after concrete inspect/decode/reap succeeds; public actions expose no hook."""
    return FixedDiscoverySeal(_ISSUER, container, binding, runtime_pid, raw)
