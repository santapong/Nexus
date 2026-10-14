"""Closed cleanup inspection descriptions never substitute for native authorization."""

import json

import pytest
from pydantic import ValidationError

from nexus.builder.contained_cleanup import (
    CleanupDeadline,
    CleanupIdentity,
    cleanup_argv,
    decode_inventory,
    decode_stopped,
)
from nexus.tests.contained_cleanup_fixture import identity, inspection, inventory


def test_exact_stopped_capture_and_empty_inventory() -> None:
    value = identity()
    assert decode_inventory(inventory(), value) is True
    assert decode_inventory(b"", value) is False
    assert decode_stopped(inspection(), value) == value
    for kind in ("inventory", "inspect", "remove"):
        argv = cleanup_argv(kind, value)
        assert argv[:3] == ("/usr/bin/podman", "--remote=false", "--cgroup-manager=cgroupfs")
        assert "--force" not in argv
    assert cleanup_argv("remove", value)[-1] == value.container_id


@pytest.mark.parametrize(
    "field,value",
    [
        ("container_id", "c" * 64),
        ("image_id", "c" * 64),
        ("company_id", "00000000-0000-0000-0000-000000000003"),
        ("action_id", "00000000-0000-0000-0000-000000000003"),
        ("container_name", "nexus-builder-" + "c" * 32),
        ("running", True),
        ("running", "false"),
        ("extra", "pass"),
    ],
)
def test_spliced_or_nonstopped_inspection_denies(field: str, value: object) -> None:
    row = json.loads(inspection())
    row[field] = value
    with pytest.raises(ValueError):
        decode_stopped(json.dumps(row).encode(), identity())


@pytest.mark.parametrize("raw", [b'{"container_id":"a","container_id":"a"}', b"x" * 65537])
def test_incomplete_duplicate_or_overflow_inspection_denies(raw: bytes) -> None:
    with pytest.raises(ValueError):
        decode_stopped(raw, identity())


@pytest.mark.parametrize(
    "variation", ["duplicate", "wrong_name", "name_collision", "unknown", "many", "overflow"]
)
def test_inventory_incomplete_or_ambiguous_never_proves_absence(variation: str) -> None:
    row = json.loads(inventory())
    if variation == "duplicate":
        raw = inventory() * 2
    elif variation == "wrong_name":
        raw = json.dumps(row | {"container_name": "other"}).encode()
    elif variation == "name_collision":
        raw = json.dumps(row | {"container_id": "c" * 64}).encode()
    elif variation == "unknown":
        raw = json.dumps(row | {"pass": True}).encode()
    elif variation == "many":
        raw = b"{}\n" * 513
    else:
        raw = b"x" * 65537
    with pytest.raises(ValueError):
        decode_inventory(raw, identity())


@pytest.mark.parametrize(
    "started,end", [(True, 5_000_001), (0, 5_000_001), (1, 1), (1, 5_000_002), (1.0, 5_000_001)]
)
def test_cleanup_deadline_rejects_reset_coercion_or_unbounded(started: object, end: object) -> None:
    with pytest.raises(ValidationError):
        CleanupDeadline.model_validate({"started_us": started, "end_us": end})


def test_copied_name_is_reconstructed_before_argv() -> None:
    copied = identity().model_copy(update={"container_name": "foreign"})
    with pytest.raises(ValueError):
        cleanup_argv("remove", copied)
    with pytest.raises(ValidationError):
        CleanupIdentity.model_validate(identity().model_dump() | {"permit": True})


@pytest.mark.parametrize("running", [0, 0.0])
def test_numeric_false_cannot_qualify_stopped_state(running: object) -> None:
    row = json.loads(inspection()) | {"running": running}
    with pytest.raises(ValueError):
        decode_stopped(json.dumps(row).encode(), identity())
