"""Pinned actual Podman stopped-object compatibility; tests issue no engine command."""

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest

from nexus.builder.contained_cleanup import STOPPED_FORMAT, CleanupIdentity, decode_stopped
from nexus.builder.contained_discovery import DISCOVERY_FORMAT, DiscoveryObject
from nexus.builder.contained_engine import INSPECT_FORMAT
from nexus.builder.contained_observer_io import INSPECT_JSON

FIXTURE = (
    Path(__file__).parents[1] / "fixtures/contained-inspect-v1/stopped-template-reproduction.json"
)


def recorded() -> tuple[str, str, dict[str, object]]:
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "23f1dfc6eb0fd79511bb206b83cd64fbfab8f294d7dafed31819ab919276f5ba"
    )
    receipt = json.loads(raw)
    before, after = receipt["rows"]
    assert before["exit_code"] == 125 and after["exit_code"] == 0
    assert before["stdout_utf8"] == '{"container_id":'
    assert "can't evaluate field Id" in before["stderr_utf8"] and not after["stderr_utf8"]
    assert before["argv"][:5] == after["argv"][:5]
    assert before["argv"][6:] == after["argv"][6:]
    old, corrected = before["argv"][5], after["argv"][5]
    assert corrected == old.replace("json .Id", "json .ID")
    return old, corrected, cast(dict[str, object], json.loads(after["stdout_utf8"]))


@pytest.mark.parametrize(
    "template", [DISCOVERY_FORMAT, INSPECT_FORMAT, INSPECT_JSON, STOPPED_FORMAT]
)
def test_each_fixed_inspect_uses_the_actually_compatible_go_field(template: str) -> None:
    original, corrected, body = recorded()
    assert corrected == DISCOVERY_FORMAT
    assert "{{json .ID}}" in template and "{{json .Id}}" not in template
    assert template != original
    assert INSPECT_FORMAT == INSPECT_JSON
    assert body["container_id"] == (
        "d5cfbfa911212790e9d5cfc05b7e218df8bed603a15f6788b292875511effff8"
    )


def test_real_corrected_stopped_reply_does_not_become_live_discovery() -> None:
    _, _, body = recorded()
    assert body["running"] is False and body["payload_pid"] == body["conmon_pid"] == 0
    with pytest.raises(ValueError):
        DiscoveryObject.model_validate_json(json.dumps(body))


@pytest.mark.parametrize("field", [None, "container_id", "company_id", "action_id", "image_id"])
def test_actual_stopped_metadata_projection_keeps_exact_cleanup_binding(field: str | None) -> None:
    _, _, body = recorded()
    # A nominated field projection tests the Python adapter, not an unexecuted Go renderer.
    expected = CleanupIdentity.model_validate_json(
        json.dumps(
            {
                key: value
                for key, value in body.items()
                if key not in {"running", "payload_pid", "conmon_pid"}
            }
        )
    )
    projected = {
        key: value for key, value in body.items() if key not in {"payload_pid", "conmon_pid"}
    }
    if field is None:
        assert decode_stopped(json.dumps(projected).encode(), expected) == expected
    else:
        projected[field] = (
            "f" * 64
            if field in {"container_id", "image_id"}
            else ("00000000-0000-0000-0000-000000000008")
        )
        with pytest.raises(ValueError):
            decode_stopped(json.dumps(projected).encode(), expected)
