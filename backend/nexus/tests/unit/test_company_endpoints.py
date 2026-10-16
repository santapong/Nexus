"""Pure server endpoint configuration: injected fake credentials only, no client or wire."""

from dataclasses import FrozenInstanceError, replace

import httpx2
import pytest
from pydantic import SecretStr

from nexus.core.llm.company_endpoints import ServerEndpointBinding, SettingsEndpointResolver
from nexus.settings import Settings

OPENAI_KEY = "unit-openai-not-a-real-credential"
GOOGLE_KEY = "unit-google-not-a-real-credential"


def configured_settings(*, openai: str = OPENAI_KEY, google: str = GOOGLE_KEY) -> Settings:
    return Settings(_env_file=None, openai_api_key=openai, google_api_key=google)


def binding(provider: str = "openai") -> ServerEndpointBinding:
    return ServerEndpointBinding(
        endpoint_id=f"{provider}.official.v1",
        provider=provider,
        api_family="openai_responses" if provider == "openai" else "google_generate_content",
        base_url="https://api.openai.com/v1"
        if provider == "openai"
        else "https://generativelanguage.googleapis.com",
        timeout_seconds=30,
    )


@pytest.mark.parametrize("provider", ["openai", "google"])
async def test_exact_official_binding_reads_injected_key_without_constructing_client(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_client(*args: object, **kwargs: object) -> None:
        raise AssertionError("Endpoint resolution must construct no HTTP client")

    monkeypatch.setattr(httpx2, "AsyncClient", no_client)
    selected = binding(provider)
    resolver = SettingsEndpointResolver(configured_settings(), (selected,))
    endpoint = await resolver.resolve(selected.endpoint_id)
    assert (endpoint.endpoint_id, endpoint.provider, endpoint.api_family, endpoint.base_url) == (
        selected.endpoint_id,
        selected.provider,
        selected.api_family,
        selected.base_url,
    )
    assert endpoint.api_key == SecretStr(OPENAI_KEY if provider == "openai" else GOOGLE_KEY)
    assert endpoint.timeout_seconds == 30 and endpoint.transport is None
    assert OPENAI_KEY not in repr(resolver) + repr(endpoint)
    assert GOOGLE_KEY not in repr(resolver) + repr(endpoint)
    assert str(endpoint.api_key) == "**********"


async def test_credentials_are_runtime_values_not_cached_and_missing_never_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "unit-environment-must-not-be-used")
    settings = configured_settings()
    resolver = SettingsEndpointResolver(settings, (binding(), binding("google")))
    first = await resolver.resolve("openai.official.v1")
    settings.openai_api_key = "unit-rotated-fake-credential"
    second = await resolver.resolve("openai.official.v1")
    assert first is not second
    assert first.api_key == SecretStr(OPENAI_KEY)
    assert second.api_key == SecretStr("unit-rotated-fake-credential")
    settings.openai_api_key = ""
    with pytest.raises(ValueError, match="credential"):
        await resolver.resolve("openai.official.v1")
    assert (await resolver.resolve("google.official.v1")).api_key == SecretStr(GOOGLE_KEY)


@pytest.mark.parametrize("key", ["", " ", "\t", " key", "key ", "key\nvalue", "key\rvalue"])
async def test_missing_or_malformed_credential_fails_closed_without_echo(key: str) -> None:
    resolver = SettingsEndpointResolver(configured_settings(openai=key), (binding(),))
    with pytest.raises(ValueError, match="credential") as error:
        await resolver.resolve("openai.official.v1")
    assert OPENAI_KEY not in str(error.value) and GOOGLE_KEY not in str(error.value)


@pytest.mark.parametrize(
    "endpoint_id", ["", "unknown", "OPENAI.official.v1", "https://api.openai.com"]
)
async def test_unknown_endpoint_ids_never_discover_or_fall_back(endpoint_id: str) -> None:
    resolver = SettingsEndpointResolver(configured_settings(), (binding(),))
    with pytest.raises(ValueError, match="endpoint"):
        await resolver.resolve(endpoint_id)


def test_empty_duplicate_and_nonbinding_configuration_denied() -> None:
    settings = configured_settings()
    with pytest.raises(ValueError, match="binding"):
        SettingsEndpointResolver(settings, ())
    with pytest.raises(ValueError, match="duplicate"):
        SettingsEndpointResolver(
            settings, (binding(), replace(binding("google"), endpoint_id="openai.official.v1"))
        )
    with pytest.raises(ValueError, match="binding"):
        SettingsEndpointResolver(settings, (object(),))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "provider,family",
    [
        ("openai", "google_generate_content"),
        ("google", "openai_responses"),
        ("openai", "openai_chat"),
        ("anthropic", "openai_responses"),
        ("OpenAI", "openai_responses"),
    ],
)
def test_provider_family_is_one_exact_supported_pair(provider: str, family: str) -> None:
    with pytest.raises(ValueError, match="provider"):
        replace(binding(), provider=provider, api_family=family)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.openai.com/v1",
        "https://api.openai.com.evil.invalid/v1",
        "https://credential@api.openai.com/v1",
        "https://api.openai.com:444/v1",
        "https://api.openai.com:443/v1",
        "https://api.openai.com/v1?key=secret",
        "https://api.openai.com/v1#fragment",
        "https://api.openai.com/v1/",
        "https://api.openai.com/v1/chat/completions",
        "https://generativelanguage.googleapis.com",
    ],
)
def test_openai_url_must_be_exact_official_canonical_base(url: str) -> None:
    with pytest.raises(ValueError, match="official"):
        replace(binding(), base_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "http://generativelanguage.googleapis.com",
        "https://generativelanguage.googleapis.com:444",
        "https://credential@generativelanguage.googleapis.com",
        "https://generativelanguage.googleapis.com?key=x",
        "https://generativelanguage.googleapis.com#fragment",
        "https://generativelanguage.googleapis.com/v1beta",
        "https://api.openai.com/v1",
    ],
)
def test_google_url_must_be_exact_official_canonical_base(url: str) -> None:
    with pytest.raises(ValueError, match="official"):
        replace(binding("google"), base_url=url)


@pytest.mark.parametrize(
    "timeout",
    [0, -1, 121, 10**1000, float("nan"), float("inf"), float("-inf"), True, False, "30", None],
)
def test_timeout_denies_nonfinite_wrong_type_or_out_of_existing_bounds(timeout: object) -> None:
    with pytest.raises(ValueError, match="timeout"):
        replace(binding(), timeout_seconds=timeout)  # type: ignore[arg-type]


@pytest.mark.parametrize("timeout", [0.001, 30, 120])
async def test_original_adapter_timeout_bounds_are_retained(timeout: float) -> None:
    selected = replace(binding(), timeout_seconds=timeout)
    resolver = SettingsEndpointResolver(configured_settings(), (selected,))
    assert (await resolver.resolve(selected.endpoint_id)).timeout_seconds == timeout


def test_bindings_are_frozen_and_invalid_identifier_cannot_enter_mapping() -> None:
    selected = binding()
    with pytest.raises(FrozenInstanceError):
        selected.base_url = "https://untrusted.invalid"  # type: ignore[misc]
    for endpoint_id in ("", " leading", "a/b", "a?b", "a\nb", "a" * 129):
        with pytest.raises(ValueError, match="identifier"):
            replace(selected, endpoint_id=endpoint_id)
