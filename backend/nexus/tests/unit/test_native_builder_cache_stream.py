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


async def _event(event: object) -> None:
    import threading

    assert isinstance(event, threading.Event)
    async with asyncio.timeout(3):
        while not event.is_set():
            await asyncio.sleep(0)


# This >50-line test keeps the real created fd, cancellation and terminal worker cleanup
# in one try/finally so a failed assertion cannot leak its nominated file operation.
async def test_cancel_after_open_create_waits_for_exact_owned_fd_before_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import os
    import threading

    destination = tmp_path / "cache.tar"
    foreign = tmp_path / "cache.tar.pending-other"
    foreign.write_bytes(b"foreign")
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    real = os.open
    descriptors: list[int] = []

    def delayed(path: str | os.PathLike[str], flags: int, mode: int = 0o777) -> int:
        fd = real(path, flags, mode)
        if not str(path).startswith(str(destination) + ".pending-"):
            return fd
        descriptors.append(fd)
        entered.set()
        try:
            if not release.wait(2):
                raise TimeoutError("finite open nominee")
            return fd
        finally:
            finished.set()

    monkeypatch.setattr(os, "open", delayed)
    task = asyncio.create_task(cache_stream(asyncio.StreamReader(), destination, limit=20))
    try:
        await _event(entered)
        task.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not task.done()  # Cancellation cannot discard an os.open already creating a file.
        task.cancel()  # Repeated cancellation cannot discard terminal settlement either.
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not destination.exists() and tuple(tmp_path.glob("*.pending-*")) == (foreign,)
        with pytest.raises(OSError):
            os.fstat(descriptors[0])
    finally:
        release.set()
        await _event(finished)
        await asyncio.gather(task, return_exceptions=True)
        from contextlib import suppress

        for fd in descriptors:
            # Original failing implementation may have lost this exact test fd.
            with suppress(OSError):
                os.close(fd)


async def test_cancel_after_link_commit_waits_and_rolls_back_only_owned_final(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import os
    import threading

    destination = tmp_path / "cache.tar"
    foreign = tmp_path / "cache.tar.pending-other"
    foreign.write_bytes(b"foreign")
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    real = os.link

    def delayed(source: Path, target: Path, *, follow_symlinks: bool) -> None:
        real(source, target, follow_symlinks=follow_symlinks)
        entered.set()
        try:
            if not release.wait(2):
                raise TimeoutError("finite link nominee")
        finally:
            finished.set()

    monkeypatch.setattr(os, "link", delayed)
    reader = asyncio.StreamReader()
    reader.feed_data(b"complete")
    reader.feed_eof()
    task = asyncio.create_task(cache_stream(reader, destination, limit=20))
    try:
        await _event(entered)
        task.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not destination.exists() and tuple(tmp_path.glob("*.pending-*")) == (foreign,)
    finally:
        release.set()
        await _event(finished)
        await asyncio.gather(task, return_exceptions=True)


# This >50-line test keeps the live stream wrapper and finite thread gate beside
# its final ownership assertions and unconditional event release.
async def test_cancel_during_live_write_never_closes_the_busy_stream(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import os
    import threading
    from typing import BinaryIO, cast

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    closed_while_busy: list[bool] = []
    real = os.fdopen

    class File:
        busy = False

        def __init__(self, raw: BinaryIO) -> None:
            self.raw = raw

        def write(self, value: bytes) -> int:
            self.busy = True
            entered.set()
            try:
                if not release.wait(2):
                    raise TimeoutError("finite write nominee")
                return self.raw.write(value)
            finally:
                self.busy = False
                finished.set()

        def close(self) -> None:
            closed_while_busy.append(self.busy)
            self.raw.close()

        def flush(self) -> None:
            self.raw.flush()

        def fileno(self) -> int:
            return self.raw.fileno()

        def __enter__(self) -> "File":
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    def opened(fd: int, mode: str) -> BinaryIO:
        return cast(BinaryIO, File(cast(BinaryIO, real(fd, mode))))

    monkeypatch.setattr(os, "fdopen", opened)
    reader = asyncio.StreamReader()
    reader.feed_data(b"partial")
    destination = tmp_path / "cache.tar"
    task = asyncio.create_task(cache_stream(reader, destination, limit=20))
    try:
        await _event(entered)
        task.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not task.done() and not closed_while_busy
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed_while_busy and not any(closed_while_busy)
        assert not destination.exists() and not tuple(tmp_path.glob("*.pending-*"))
    finally:
        release.set()
        await _event(finished)
        await asyncio.gather(task, return_exceptions=True)


async def test_cancelled_link_error_preserves_original_cancel_and_foreign_destination(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import os
    import threading

    destination = tmp_path / "cache.tar"
    destination.write_bytes(b"foreign immutable final")
    other = tmp_path / "cache.tar.pending-foreign"
    other.write_bytes(b"foreign stage")
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    real = os.link

    def delayed(source: Path, target: Path, *, follow_symlinks: bool) -> None:
        entered.set()
        try:
            if not release.wait(2):
                raise TimeoutError("finite conflicting link nominee")
            real(source, target, follow_symlinks=follow_symlinks)
        finally:
            finished.set()

    monkeypatch.setattr(os, "link", delayed)
    reader = asyncio.StreamReader()
    reader.feed_data(b"new")
    reader.feed_eof()
    task = asyncio.create_task(cache_stream(reader, destination, limit=20))
    try:
        await _event(entered)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError) as captured:
            await task
        assert any("FileExistsError" in note for note in captured.value.__notes__)
        assert destination.read_bytes() == b"foreign immutable final"
        assert other.read_bytes() == b"foreign stage"
        assert tuple(tmp_path.glob("*.pending-*")) == (other,)
    finally:
        release.set()
        await _event(finished)
        await asyncio.gather(task, return_exceptions=True)
