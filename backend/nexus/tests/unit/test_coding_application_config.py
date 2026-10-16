"""Actual strict configuration and private-file identity, never actor/effect permission."""

import hashlib
from pathlib import Path

import pytest

from nexus.builder.contained_query import clock_us
from nexus.execution.coding_application_config import parse_coding_config
from nexus.execution.coding_application_files import load_coding_config
from nexus.tests.unit.coding_application_fixture import configuration


def test_exact_nested_configuration_wire_and_all_role_bindings(tmp_path: Path) -> None:
    value = configuration(tmp_path)
    raw = value.model_dump_json(by_alias=True).encode()
    assert parse_coding_config(raw, hashlib.sha256(raw).hexdigest()) == value
    assert value.catalog is value.planning.catalog and value.goal == value.planning.goal
    assert value.admission.slots[1].tool.resource == "model:" + value.registry_id


@pytest.mark.parametrize(
    "fault", ["hash", "duplicate", "nonfinite", "role", "model", "source", "alias-root"]
)
def test_configuration_cannot_supply_unbound_or_ambiguous_c_authority(
    tmp_path: Path, fault: str
) -> None:
    value = configuration(tmp_path)
    if fault == "role":
        value = value.model_copy(update={"role_policy": value.planning.role_policy})
    elif fault == "model":
        value = value.model_copy(update={"registry_id": value.planning.registry_id})
    elif fault == "source":
        value = value.model_copy(update={"code_sources": value.code_sources[:1]})
    elif fault == "alias-root":
        value = value.model_copy(update={"prepared_root": value.planning.storage.prepared_root})
    raw = value.model_dump_json(by_alias=True).encode()
    if fault == "duplicate":
        raw = b'{"schema_version":"wrong",' + raw[1:]
    elif fault == "nonfinite":
        raw = raw[:-1] + b',"extra":NaN}'
    with pytest.raises(ValueError):
        parse_coding_config(raw, "a" * 64 if fault == "hash" else hashlib.sha256(raw).hexdigest())


def test_private_real_config_is_immutable_and_original_parent_bound(tmp_path: Path) -> None:
    parent = tmp_path / "operator"
    parent.mkdir(mode=0o700)
    path = parent / "coding.json"
    raw = configuration(tmp_path / "data").model_dump_json(by_alias=True).encode()
    path.write_bytes(raw)
    path.chmod(0o600)
    pinned = load_coding_config(
        path, hashlib.sha256(raw).hexdigest(), end_us=clock_us() + 5_000_000
    )
    pinned.require_current(end_us=clock_us() + 5_000_000)
    path.chmod(0o644)
    with pytest.raises(ValueError):
        pinned.require_current(end_us=clock_us() + 5_000_000)
