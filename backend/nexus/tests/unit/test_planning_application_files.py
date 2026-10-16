"""Real private operator configuration reads; no account, SDK or database effects."""

import hashlib
import os
from pathlib import Path

import pytest

from nexus.company.management.planning_native_facts import read_end
from nexus.execution.planning_application_files import load_planning_config
from nexus.tests.unit.planning_application_fixture import configuration


def config_file(root: Path) -> tuple[Path, str]:
    parent = root / "operator"
    parent.mkdir(mode=0o700)
    path = parent / "planning.json"
    raw = configuration(root).model_dump_json(by_alias=True).encode()
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
    return path, hashlib.sha256(raw).hexdigest()


def test_exact_private_config_and_original_file_identity_are_retained(tmp_path: Path) -> None:
    path, digest = config_file(tmp_path)
    loaded = load_planning_config(path, digest, end_us=read_end())
    assert loaded.value.goal.company_id == loaded.value.catalog.company_id
    loaded.require_current(end_us=read_end())
    replacement = path.with_suffix(".replacement")
    replacement.write_bytes(path.read_bytes())
    replacement.chmod(0o600)
    replacement.replace(path)
    with pytest.raises(ValueError, match="original configuration changed"):
        loaded.require_current(end_us=read_end())


@pytest.mark.parametrize("fault", ["public-parent", "public-file", "symlink", "wrong-hash"])
def test_unsafe_or_crossed_configuration_is_not_adopted(tmp_path: Path, fault: str) -> None:
    path, digest = config_file(tmp_path)
    if fault == "public-parent":
        path.parent.chmod(0o755)
    elif fault == "public-file":
        path.chmod(0o644)
    elif fault == "symlink":
        link = path.with_suffix(".link")
        link.symlink_to(path)
        path = link
    else:
        digest = "f" * 64
    with pytest.raises((ValueError, OSError)):
        load_planning_config(path, digest, end_us=read_end())


def test_expired_original_operator_window_cannot_read_config(tmp_path: Path) -> None:
    path, digest = config_file(tmp_path)
    with pytest.raises(TimeoutError):
        load_planning_config(path, digest, end_us=1)


def test_original_read_failure_is_retained_when_owned_close_also_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.execution import planning_application_files as module

    path, _ = config_file(tmp_path)
    first = TimeoutError("original finite acquisition expired")
    real_close = os.close

    def expiry(end_us: int) -> None:
        raise first

    def failed_close(descriptor: int) -> None:
        real_close(descriptor)
        raise OSError("supplied owned-close failure")

    monkeypatch.setattr(module, "require_time", expiry)
    monkeypatch.setattr(os, "close", failed_close)
    with pytest.raises(TimeoutError) as caught:
        module._read_owned(path, end_us=1)
    assert caught.value is first
    assert vars(first)["_nexus_planning_secondary"] == "OSError"


def test_hardlinked_private_configuration_is_denied(tmp_path: Path) -> None:
    path, digest = config_file(tmp_path)
    path.with_suffix(".hardlink").hardlink_to(path)
    with pytest.raises(ValueError, match="private ordinary"):
        load_planning_config(path, digest, end_us=read_end())


def test_namespace_replacement_during_read_is_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, digest = config_file(tmp_path)
    read = os.read
    swapped = False

    def replace(descriptor: int, size: int) -> bytes:
        nonlocal swapped
        raw = read(descriptor, size)
        if not swapped:
            swapped = True
            replacement = path.with_suffix(".replacement")
            replacement.write_bytes(path.read_bytes())
            replacement.chmod(0o600)
            replacement.replace(path)
        return raw

    monkeypatch.setattr(os, "read", replace)
    with pytest.raises(ValueError, match="configuration changed during acquisition"):
        load_planning_config(path, digest, end_us=read_end())


def test_parent_namespace_replacement_cannot_rebind_pinned_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, digest = config_file(tmp_path)
    payload = path.read_bytes()
    original_read = os.read
    replaced = False

    def move_parent(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        raw = original_read(descriptor, size)
        if not replaced:
            replaced = True
            path.parent.rename(tmp_path / "original-operator")
            path.parent.mkdir(mode=0o700)
            path.write_bytes(payload)
            path.chmod(0o600)
        return raw

    monkeypatch.setattr(os, "read", move_parent)
    with pytest.raises(ValueError, match="namespace changed"):
        load_planning_config(path, digest, end_us=read_end())
