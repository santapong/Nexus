"""Regression from actual finite-scope ENODATA: only qualified user context permits absence."""

import errno
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from nexus.builder.contained_contracts import (
    KernelScopeFacts,
    ParentObservation,
    ScopeExpectation,
    SystemdScopeFacts,
    UserManagerObservation,
)
from nexus.builder.contained_kernel import collect_kernel
from nexus.builder.contained_scope import validate_current_scope
from nexus.builder.systemd_scope_provider import SystemdScopeProvider, decode_records
from nexus.builder.user_parent_identity import (
    USER_PARENT_METHOD_SHA256,
    USER_PARENT_PROVIDER_VERSION,
)
from nexus.tests.unit.test_contained_kernel import setup_kernel_tree
from nexus.tests.unit.test_contained_scope import (
    expectation,
    kernel_facts,
    unit_facts,
    user_manager,
)
from nexus.tests.unit.test_systemd_scope_provider import FakeReader, read_kernel, reports


def test_actual_missing_marker_remains_absence_and_new_versioned_description() -> None:
    kernel = KernelScopeFacts.model_validate(
        kernel_facts().model_dump() | {"delegation_marker": "absent_user_manager"}
    )
    observed = validate_current_scope(expectation(), unit_facts(), kernel, 11_000_000, 12_000_000)
    assert observed.kernel.delegation_marker == "absent_user_manager"
    assert observed.schema_version == "nexus.builder.parent-observation.v2"
    assert observed.provider_version == USER_PARENT_PROVIDER_VERSION
    assert observed.provider_method_sha256 == USER_PARENT_METHOD_SHA256


@pytest.mark.parametrize(
    "field,value",
    [
        ("manager", "system"),
        ("version", "260"),
        ("version", None),
        ("uid", False),
        ("uid", None),
        ("uid", 0),
        ("query_route", "caller_bus"),
    ],
)
def test_unknown_or_unqualified_manager_description_denies(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        UserManagerObservation.model_validate(user_manager().model_dump() | {field: value})


@pytest.mark.parametrize("value", [False, True, "missing", None])
def test_boolean_or_unknown_marker_cannot_pretend_qualified_delegation(value: object) -> None:
    with pytest.raises(ValidationError):
        KernelScopeFacts.model_validate(kernel_facts().model_dump() | {"delegation_marker": value})


@pytest.mark.parametrize("error", [errno.EACCES, errno.ENOTSUP, errno.EIO])
def test_other_xattr_errors_remain_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: int
) -> None:
    setup_kernel_tree(tmp_path, monkeypatch)

    def failed(fd: int, name: str) -> bytes:
        raise OSError(error, "intentional retained xattr error")

    monkeypatch.setattr(os, "getxattr", failed)
    with pytest.raises(OSError) as failure:
        collect_kernel(expectation(), user_manager())
    assert failure.value.errno == error


@pytest.mark.parametrize("raw", [b"", b"0", b"1\x00", b"true"])
def test_malformed_or_false_actual_markers_remain_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: bytes
) -> None:
    group = setup_kernel_tree(tmp_path, monkeypatch)
    os.setxattr(group, "user.delegate", raw)
    with pytest.raises(ValueError):
        collect_kernel(expectation(), user_manager())


def test_absence_with_false_delegate_or_foreign_manager_uid_still_denies() -> None:
    kernel = KernelScopeFacts.model_validate(
        kernel_facts().model_dump() | {"delegation_marker": "absent_user_manager"}
    )
    false_unit = unit_facts().model_copy(update={"delegated": False})
    with pytest.raises(ValueError):
        validate_current_scope(expectation(), false_unit, kernel, 11_000_000, 12_000_000)
    foreign = UserManagerObservation.model_validate(user_manager().model_dump() | {"uid": 1001})
    for unit, row in (
        (unit_facts().model_copy(update={"user_manager": foreign}), kernel),
        (unit_facts(), kernel.model_copy(update={"user_manager": foreign})),
    ):
        with pytest.raises(ValueError):
            validate_current_scope(expectation(), unit, row, 11_000_000, 12_000_000)


def test_matching_foreign_hierarchy_cannot_qualify_same_uid() -> None:
    path = expectation().cgroup_path.replace("user-1000.slice", "user-1001.slice")
    expected = ScopeExpectation.model_validate(expectation().model_dump() | {"cgroup_path": path})
    unit = SystemdScopeFacts.model_validate(unit_facts().model_dump() | {"cgroup_path": path})
    kernel = KernelScopeFacts.model_validate(
        kernel_facts().model_dump()
        | {
            "cgroup_path": path,
            "self_cgroup_path": path,
            "delegation_marker": "absent_user_manager",
        }
    )
    with pytest.raises(ValueError, match="hierarchy"):
        validate_current_scope(expected, unit, kernel, 11_000_000, 12_000_000)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "nexus.builder.parent-observation.v1"),
        ("provider_method_sha256", "a" * 64),
    ],
)
def test_original_or_spliced_provider_description_cannot_be_relabelled_v2(
    field: str, value: object
) -> None:
    observed = validate_current_scope(
        expectation(), unit_facts(), kernel_facts(), 11_000_000, 12_000_000
    )
    with pytest.raises(ValidationError):
        ParentObservation.model_validate(observed.model_dump() | {field: value})


@pytest.mark.parametrize(
    "raw",
    [
        b'{"type":"u","data":1000}',
        b'{"type":"u","data":[]}',
        b'{"type":"u","data":[1000,1001]}',
        b'{"type":"u","data":[true]}',
        b'{"type":"u","data":[null]}',
        b'{"type":"u","data":[-1]}',
        b'{"type":"u","data":[4294967296]}',
    ],
)
def test_manager_uid_native_method_array_is_exact_one_uint32(raw: bytes) -> None:
    with pytest.raises(ValueError):
        decode_records(raw, ("u",))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "index,body", [(0, b'{"type":"u","data":[1001]}'), (1, b'{"type":"s","data":"260"}')]
)
async def test_current_foreign_uid_or_unsupported_version_denies_before_scope_reads(
    index: int, body: bytes
) -> None:
    raw = reports()
    raw[index] = body
    reader = FakeReader(raw)
    provider = SystemdScopeProvider(
        reader=reader, kernel_reader=read_kernel, clock_us=lambda: 11_000_000
    )
    with pytest.raises(ValueError):
        await provider.observe(expectation())
    assert len(reader.calls) <= 2


@pytest.mark.asyncio
async def test_current_manager_context_is_reread_after_good_observation() -> None:
    changed = reports()
    changed[1] = b'{"type":"s","data":"260"}'
    reader = FakeReader(reports() + changed)
    # The successful observation now rechecks its clock after metadata; the failed
    # fresh manager read also records its own final clock. Keep the same denial.
    clock = iter((11_000_000, 12_000_000, 12_000_000, 13_000_000, 13_000_000))
    provider = SystemdScopeProvider(
        reader=reader, kernel_reader=read_kernel, clock_us=lambda: next(clock)
    )
    await provider.observe(expectation())
    with pytest.raises(ValueError):
        await provider.observe(expectation())
    assert len(reader.calls) == 7
