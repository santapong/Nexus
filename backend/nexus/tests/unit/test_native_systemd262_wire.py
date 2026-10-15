"""Captured daemon version bytes exercise the real parser; no scope or process is launched."""

import errno
import os
from pathlib import Path

import pytest

from nexus.builder.contained_contracts import KernelScopeFacts, UserManagerObservation
from nexus.builder.systemd_scope_provider import SystemdScopeProvider
from nexus.builder.user_parent_identity import CURRENT_USER_PARENT_262_PROVIDER_VERSION
from nexus.tests.unit.test_contained_scope import expectation, kernel_facts
from nexus.tests.unit.test_systemd_scope_provider import FakeReader, reports

# Exact complete version reply from raw-parent.json SHA256 2cdeffe212fb4eb0a640acb9febfd5e7f
# cc09395bad82007a802ef8b81184bf1, collected 2026-10-15. Other facts below are synthetic.
CAPTURED_262_VERSION = b'{"type":"s","data":"262-1"}\n'


@pytest.mark.asyncio
async def test_actual_captured_262_version_passes_real_five_reply_parser() -> None:
    raw = reports()
    raw[1] = CAPTURED_262_VERSION
    reader = FakeReader(raw)

    async def kernel() -> KernelScopeFacts:
        return kernel_facts().model_copy(
            update={
                "user_manager": UserManagerObservation(
                    manager="user", version="262-1", uid=1000, query_route="fixed_local_user_bus"
                )
            }
        )

    ticks = iter((11_000_000, 12_000_000, 12_000_000))
    row = await SystemdScopeProvider(
        reader=reader, kernel_reader=kernel, clock_us=lambda: next(ticks)
    ).observe(expectation())
    assert len(reader.calls) == 5
    assert row.unit.user_manager.version == row.kernel.user_manager.version == "262-1"
    assert row.provider_version == CURRENT_USER_PARENT_262_PROVIDER_VERSION


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "index,body",
    [
        (0, b'{"type":"u","data":[1001]}'),
        (0, b'{"type":"u","data":[true]}'),
        (0, b'{"type":"u","data":[0]}'),
        (1, b'{"type":"s","data":"262-2"}'),
        (1, b'{"type":"s","data":"262-1.extra"}'),
        (1, b'{"type":"s","data":"system 262-1"}'),
    ],
)
async def test_native_wrong_uid_or_version_denies_before_scope_queries(
    index: int, body: bytes
) -> None:
    raw = reports()
    raw[1] = CAPTURED_262_VERSION
    raw[index] = body
    reader = FakeReader(raw)

    async def forbidden_kernel() -> KernelScopeFacts:
        pytest.fail("Denied manager reached kernel reader")

    with pytest.raises(ValueError):
        await SystemdScopeProvider(
            reader=reader, kernel_reader=forbidden_kernel, clock_us=lambda: 11_000_000
        ).observe(expectation())
    assert len(reader.calls) == (1 if body == b'{"type":"u","data":[true]}' else 2)


@pytest.mark.asyncio
async def test_262_diagnostic_final_clock_uses_same_original_three_second_end() -> None:
    from nexus.tests.unit.test_native_systemd262_profiles import manager

    raw = reports()
    raw[1] = CAPTURED_262_VERSION

    async def kernel() -> KernelScopeFacts:
        return kernel_facts().model_copy(update={"user_manager": manager("262-1")})

    clock = iter((11_000_000, 12_000_000, 14_000_001))
    provider = SystemdScopeProvider(
        reader=FakeReader(raw), kernel_reader=kernel, clock_us=lambda: next(clock)
    )
    with pytest.raises(ValueError, match="original deadline"):
        await provider.observe(expectation())


@pytest.mark.parametrize("version", ["261.2-1", "262-1"])
@pytest.mark.parametrize("present", [False, True])
def test_real_owned_xattr_returns_only_actual_present_or_enodata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str, present: bool
) -> None:
    from nexus.builder.contained_kernel import collect_kernel
    from nexus.tests.unit.test_contained_kernel import setup_kernel_tree
    from nexus.tests.unit.test_native_systemd262_profiles import manager

    group = setup_kernel_tree(tmp_path, monkeypatch)
    if not present:
        os.removexattr(group, "user.delegate")
    row = collect_kernel(expectation(), manager(version))
    assert row.user_manager.version == version
    assert row.delegation_marker == ("present_1" if present else "absent_user_manager")


@pytest.mark.parametrize("version", ["261.2-1", "262-1"])
@pytest.mark.parametrize("error", [errno.EACCES, errno.ENOTSUP, errno.EIO])
def test_other_actual_marker_read_errors_are_never_reported_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str, error: int
) -> None:
    from nexus.builder.contained_kernel import collect_kernel
    from nexus.tests.unit.test_contained_kernel import setup_kernel_tree
    from nexus.tests.unit.test_native_systemd262_profiles import manager

    setup_kernel_tree(tmp_path, monkeypatch)

    def failed(fd: int, name: str) -> bytes:
        raise OSError(error, "synthetic marker read denial")

    monkeypatch.setattr(os, "getxattr", failed)
    with pytest.raises(OSError) as failure:
        collect_kernel(expectation(), manager(version))
    assert failure.value.errno == error
