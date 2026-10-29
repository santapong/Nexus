"""The offline transport retains the endpoint's explicit timeout, without network I/O."""

import httpx2
import pytest

from nexus.core.llm.company_endpoints import ServerEndpointBinding, SettingsEndpointResolver
from nexus.settings import Settings
from nexus.tests.integration.nexus_coding_application_transport import Transport


@pytest.mark.parametrize("timeout_seconds", [2.0, 30.0])
async def test_mock_transport_preserves_current_endpoint_timeout(timeout_seconds: float) -> None:
    """A short explicit boundary stays short; the ordinary endpoint keeps its own value."""
    binding = ServerEndpointBinding(
        endpoint_id="fixture.openai",
        provider="openai",
        api_family="openai_responses",
        base_url="https://api.openai.com/v1",
        timeout_seconds=timeout_seconds,
    )
    resolver = SettingsEndpointResolver(
        Settings(_env_file=None, openai_api_key="synthetic-key-not-a-real-credential"),
        (binding,),
    )
    probe = Transport(provider="openai", content="{}", schema_comment="synthetic")
    with probe.install():
        endpoint = await resolver.resolve(binding.endpoint_id)
    assert endpoint.timeout_seconds == timeout_seconds
    assert isinstance(endpoint.transport, httpx2.MockTransport)
    assert probe.lookups == 1 and not probe.posts
