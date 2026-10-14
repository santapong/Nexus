"""Changed bytes, modes, lock pins and host paths cannot enter the Node input boundary."""

import os
from dataclasses import replace
from pathlib import Path

import pytest

from nexus.builder.node_input_files import file_digests, managed_path
from nexus.tests.node_input_support import configured_inputs


async def test_complete_ordinary_inputs_and_preserved_exec_mode_qualify(tmp_path: Path) -> None:
    config = configured_inputs(tmp_path)
    await config.revalidate()
    assert (config.cache / "ordinary").stat().st_mode & 0o777 == 0o400
    assert (config.cache / "executable").stat().st_mode & 0o777 == 0o500


@pytest.mark.parametrize("field", ["pnpm_archive", "cache_archive", "manifest"])
async def test_changed_archive_or_manifest_denied(tmp_path: Path, field: str) -> None:
    config = configured_inputs(tmp_path)
    path = getattr(config, field)
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="bytes changed"):
        await config.revalidate()


@pytest.mark.parametrize("change", ["bytes", "exec_mode", "extra", "link", "hardlink"])
async def test_current_cache_tree_changes_denied(tmp_path: Path, change: str) -> None:
    config = configured_inputs(tmp_path)
    path = config.cache / "ordinary"
    if change == "bytes":
        path.chmod(0o600)
        path.write_bytes(b"changed! fixture")
        path.chmod(0o400)
    elif change == "exec_mode":
        path.chmod(0o500)
    elif change == "extra":
        (config.cache / "unreviewed").write_text("extra")
    elif change == "link":
        path.unlink()
        path.symlink_to(config.cache / "executable")
    else:
        os.link(path, config.cache / "second")
    with pytest.raises((ValueError, OSError)):
        await config.revalidate()


@pytest.mark.parametrize("field", ["lock_sha256", "pnpm_integrity"])
async def test_independent_lock_and_sri_pins_required(tmp_path: Path, field: str) -> None:
    config = configured_inputs(tmp_path)
    value = "9" * 64 if field == "lock_sha256" else "sha512-" + "a" * 86 + "=="
    changed = replace(config, pins=config.pins.model_copy(update={field: value}))
    with pytest.raises(ValueError):
        await changed.revalidate()


def test_bound_no_follow_reads_and_mount_syntax_are_enforced(tmp_path: Path) -> None:
    path = tmp_path / "ordinary"
    path.write_bytes(b"public")
    with pytest.raises(ValueError, match="byte bounds"):
        file_digests(path, 5)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        file_digests(link, 10)
    unsafe = tmp_path / "colon:mount"
    unsafe.write_bytes(b"public")
    with pytest.raises(ValueError, match="ordinary server paths"):
        managed_path(unsafe)
