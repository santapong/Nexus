"""Actual ordinary file IO qualifies immutable publication, not a native job."""

import os
from pathlib import Path

import pytest

from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
from nexus.tests.contained_observer_fixture import identity
from nexus.tests.unit.test_contained_evidence_types import observation


@pytest.mark.asyncio
async def test_equal_replay_preserves_original_identity(tmp_path: Path) -> None:
    store = ContainmentEvidenceStore(tmp_path / "private")
    value = observation()
    ref = await store.save_once(value)
    assert await store.save_once(value) == ref
    assert await store.load_exact(ref, identity()) == value
    assert len(tuple(store.root.glob("*.json"))) == 1


@pytest.mark.asyncio
async def test_conflicting_bytes_do_not_replace_original(tmp_path: Path) -> None:
    store = ContainmentEvidenceStore(tmp_path / "private")
    value = observation()
    ref = await store.save_once(value)
    with pytest.raises(ValueError):
        await store.save_once(value.model_copy(update={"proposal_sha256": "3" * 64}))
    assert await store.load_exact(ref, identity()) == value


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("sha256", "4" * 64), ("byte_length", 1)])
async def test_ref_splice_denies(tmp_path: Path, field: str, value: object) -> None:
    store = ContainmentEvidenceStore(tmp_path / "private")
    ref = await store.save_once(observation())
    with pytest.raises(ValueError):
        await store.load_exact(ref.model_copy(update={field: value}), identity())


@pytest.mark.asyncio
async def test_current_fence_or_other_identity_denies(tmp_path: Path) -> None:
    store = ContainmentEvidenceStore(tmp_path / "private")
    ref = await store.save_once(observation())
    for field, value in (
        ("original_intent_fence", 9),
        ("result_base_sha256", "9" * 64),
        ("execution_method_sha256", "8" * 64),
    ):
        with pytest.raises(ValueError):
            await store.load_exact(ref, identity().model_copy(update={field: value}))


@pytest.mark.asyncio
async def test_pending_conflict_denies(tmp_path: Path) -> None:
    store = ContainmentEvidenceStore(tmp_path / "private")
    (store.root / (store.filename(identity()) + ".pending")).write_bytes(b"interrupted")
    with pytest.raises(FileExistsError):
        await store.save_once(observation())


@pytest.mark.asyncio
async def test_final_symlink_or_hardlink_denies(tmp_path: Path) -> None:
    for kind in ("symlink", "hardlink"):
        store = ContainmentEvidenceStore(tmp_path / kind)
        ref = await store.save_once(observation())
        final = store.root / store.filename(identity())
        if kind == "symlink":
            raw = final.read_bytes()
            final.unlink()
            target = tmp_path / "foreign"
            target.write_bytes(raw)
            final.symlink_to(target)
        else:
            os.link(final, tmp_path / "foreign-hardlink")
        with pytest.raises((ValueError, OSError)):
            await store.load_exact(ref, identity())


@pytest.mark.asyncio
async def test_original_owned_root_inode_is_pinned(tmp_path: Path) -> None:
    store = ContainmentEvidenceStore(tmp_path / "private")
    ref = await store.save_once(observation())
    store.root.rename(tmp_path / "historical")
    store.root.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="root inode"):
        await store.save_once(observation())
    with pytest.raises(ValueError, match="root inode"):
        await store.load_exact(ref, identity())


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", [False, True])
async def test_pending_written_bytes_and_inode_replacement_are_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: bool,
) -> None:
    store = ContainmentEvidenceStore(tmp_path / ("replaced" if replacement else "tampered"))
    real = os.fsync
    changed = False

    def tamper(fd: int) -> None:
        nonlocal changed
        real(fd)
        if changed:
            return
        pending = next(store.root.glob("*.pending"), None)
        if pending is None:
            return
        changed = True
        if replacement:
            pending.rename(store.root / "retained-original")
            pending.write_bytes(b"foreign replaced pending")
        else:
            pending.write_bytes(b"altered bytes")

    with monkeypatch.context() as scope:
        scope.setattr(os, "fsync", tamper)
        with pytest.raises(ValueError):
            await store.save_once(observation())
    assert not tuple(store.root.glob("*.json"))
