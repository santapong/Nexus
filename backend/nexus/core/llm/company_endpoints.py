"""Explicit server-owned official endpoints; credential lookup alone authorizes no model call."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from pydantic import SecretStr

from nexus.core.llm.company_adapter_contracts import ServerEndpoint
from nexus.settings import Settings

_OFFICIAL_BASES = MappingProxyType(
    {
        ("openai", "openai_responses"): "https://api.openai.com/v1",
        ("google", "google_generate_content"): "https://generativelanguage.googleapis.com",
    }
)


@dataclass(frozen=True, slots=True)
class ServerEndpointBinding:
    """Trusted operator metadata, never a request DTO or a place to store credentials."""

    endpoint_id: str
    provider: str
    api_family: str
    base_url: str = field(repr=False)
    timeout_seconds: float = 30

    def __post_init__(self) -> None:
        if (
            type(self.endpoint_id) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", self.endpoint_id) is None
        ):
            raise ValueError("Company endpoint identifier is invalid")
        if type(self.provider) is not str or type(self.api_family) is not str:
            raise ValueError("Company endpoint provider/API family is unsupported")
        expected = _OFFICIAL_BASES.get((self.provider, self.api_family))
        if expected is None:
            raise ValueError("Company endpoint provider/API family is unsupported")
        # Exact canonical bases exclude HTTP, userinfo, query, fragment, alternate ports,
        # aliases and foreign paths without normalizing an operator mistake into authority.
        if type(self.base_url) is not str or self.base_url != expected:
            raise ValueError("Company endpoint needs its exact official canonical base URL")
        if (
            type(self.timeout_seconds) not in (int, float)
            or not 0 < self.timeout_seconds <= 120
            or not math.isfinite(self.timeout_seconds)
        ):
            raise ValueError("Company endpoint timeout must be finite and within (0,120]")


class SettingsEndpointResolver:
    """Read the injected current credential only when resolving an exact named binding.

    No SDK/client, network lookup, fallback, application wiring or model activation occurs.
    Settings are retained by reference for deliberate credential rotation; keys are not cached.
    """

    __slots__ = ("_bindings", "_settings")

    def __init__(self, settings: Settings, bindings: tuple[ServerEndpointBinding, ...]) -> None:
        if not isinstance(settings, Settings):
            raise ValueError("Company endpoints require explicitly injected Settings")
        if type(bindings) is not tuple or not bindings:
            raise ValueError("Company endpoints require explicit server bindings")
        copied: dict[str, ServerEndpointBinding] = {}
        for binding in bindings:
            if type(binding) is not ServerEndpointBinding:
                raise ValueError("Company endpoint binding is unsupported")
            # Retain our own validated immutable metadata rather than a caller-owned object.
            selected = ServerEndpointBinding(
                binding.endpoint_id,
                binding.provider,
                binding.api_family,
                binding.base_url,
                binding.timeout_seconds,
            )
            if selected.endpoint_id in copied:
                raise ValueError("Company endpoint binding has a duplicate identifier")
            copied[selected.endpoint_id] = selected
        self._bindings: Mapping[str, ServerEndpointBinding] = MappingProxyType(copied)
        self._settings = settings

    def __repr__(self) -> str:
        return f"SettingsEndpointResolver(bindings={len(self._bindings)})"

    async def resolve(self, endpoint_id: str) -> ServerEndpoint:
        if type(endpoint_id) is not str or endpoint_id not in self._bindings:
            raise ValueError("Named company endpoint is unavailable")
        binding = self._bindings[endpoint_id]
        key = (
            self._settings.openai_api_key
            if binding.provider == "openai"
            else self._settings.google_api_key
        )
        if (
            type(key) is not str
            or not key
            or any(
                character.isspace() or ord(character) < 32 or ord(character) == 127
                for character in key
            )
        ):
            raise ValueError("Named company endpoint credential is unavailable")
        return ServerEndpoint(
            endpoint_id=binding.endpoint_id,
            provider=binding.provider,
            api_family=binding.api_family,
            base_url=binding.base_url,
            api_key=SecretStr(key),
            timeout_seconds=binding.timeout_seconds,
        )
