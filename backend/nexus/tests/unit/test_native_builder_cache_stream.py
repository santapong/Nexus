"""Export overflow/cancellation/no-overwrite leaves no mutable final cache or other-stage damage."""

import asyncio
from pathlib import Path

import pytest

from nexus.builder.cache_stream import cache_stream


async def test_binary_cache_export_verifies_hash_without_buffering_all_bytes(
    tmp_path: Path,
) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"public cache")
    reader.feed_eof()
    result = await cache_stream(reader, tmp_path / "cache.tar", limit=20)
    assert result.byte_length == 12 and (tmp_path / "cache.tar").read_bytes() == b"public cache"
    assert not tuple(tmp_path.glob("*.pending-*"))


async def test_cache_overflow_and_existing_result_preserve_other_stage(tmp_path: Path) -> None:
    destination = tmp_path / "cache.tar"
    destination.write_bytes(b"immutable original")
    other = tmp_path / "cache.tar.pending-existing"
    other.write_bytes(b"different owner stage")
    for bound, error in ((2, ValueError), (20, FileExistsError)):
        reader = asyncio.StreamReader()
        reader.feed_data(b"new public cache")
        reader.feed_eof()
        with pytest.raises(error):
            await cache_stream(reader, destination, limit=bound)
        assert (
            destination.read_bytes() == b"immutable original"
            and other.read_bytes() == b"different owner stage"
        )
        assert tuple(tmp_path.glob("*.pending-*")) == (other,)


async def test_cache_cancellation_removes_only_its_own_partial(tmp_path: Path) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"partial")
    task = asyncio.create_task(cache_stream(reader, tmp_path / "cache.tar", limit=20))
    for _ in range(100):
        if tuple(tmp_path.glob("*.pending-*")):
            break
        await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not (tmp_path / "cache.tar").exists() and not tuple(tmp_path.glob("*.pending-*"))
