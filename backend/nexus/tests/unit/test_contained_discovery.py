"""Fixed-name discovery seals full immutable ID without weakening Root ID-only inspection."""

import json

import pytest

from nexus.builder.contained_discovery import decode_discovery, discovery_argv
from nexus.tests.contained_process_fixture import binding, launch


def body() -> bytes:
    value = binding()
    return json.dumps(
        {
            "container_id": "e" * 64,
            "container_name": value.container_name,
            "company_id": str(value.company_id),
            "action_id": str(value.action_id),
            "image_id": value.image_id,
            "running": True,
            "payload_pid": 101,
            "conmon_pid": 102,
        }
    ).encode()


def test_fixed_native_name_then_exact_immutable_id() -> None:
    value = decode_discovery(body(), launch(), runtime_pid=103)
    assert value.container_id == "e" * 64 and value.runtime_pid == 103
    assert discovery_argv(binding())[-1] == binding().container_name


@pytest.mark.parametrize(
    "field,value",
    [
        ("container_name", "nexus-builder-" + "f" * 32),
        ("image_id", "f" * 64),
        ("running", False),
        ("payload_pid", True),
        ("extra", "pass"),
    ],
)
def test_wrong_identity_or_missing_live_fields_denies(field: str, value: object) -> None:
    row = json.loads(body())
    row[field] = value
    with pytest.raises(ValueError):
        decode_discovery(json.dumps(row).encode(), launch(), runtime_pid=103)


def test_duplicate_and_oversized_discovery_reply_denies() -> None:
    for raw in (b'{"running":true,"running":true}', b"x" * 65537):
        with pytest.raises(ValueError):
            decode_discovery(raw, launch(), runtime_pid=103)
