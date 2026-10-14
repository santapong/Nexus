"""Pinned SDK host-executor replacement must not kill later fixture I/O on destruction."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from dbos import DBOS

from nexus.tests import notification_durable_pg_fixture as module


async def test_sdk_destroy_uses_original_host_pool_and_restores_later_host_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await asyncio.to_thread(lambda: None)
    loop = asyncio.get_running_loop()
    original = getattr(loop, "_default_executor", None)
    assert isinstance(original, ThreadPoolExecutor)
    host = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fixture-host")
    sdk = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fixture-sdk")
    try:
        loop.set_default_executor(host)
        captured = module.capture_host_executor()
        assert captured is host
        # Simulate the inspected get_result_async SDK adoption, without DBOS
        # construction, worker startup or company/native state.
        loop.set_default_executor(sdk)

        def destroy(*, workflow_completion_timeout_sec: int) -> None:
            assert workflow_completion_timeout_sec == 5
            assert threading.current_thread().name.startswith("fixture-host")
            sdk.shutdown(wait=False, cancel_futures=True)

        monkeypatch.setattr(DBOS, "destroy", destroy)
        await module.destroy_sdk_on_host_executor(captured)
        assert getattr(loop, "_default_executor", None) is host
        assert (await asyncio.to_thread(lambda: threading.current_thread().name)).startswith(
            "fixture-host"
        )
    finally:
        loop.set_default_executor(original)
        host.shutdown(wait=True, cancel_futures=True)
        sdk.shutdown(wait=True, cancel_futures=True)


@pytest.mark.parametrize("kind", ["wrong", "missing", "closed"])
async def test_missing_wrong_or_closed_host_executor_denies_constant_safe_setup(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    original = getattr(loop, "_default_executor", None)
    pool = ThreadPoolExecutor(max_workers=1)
    if kind == "closed":
        pool.shutdown(wait=True)
    try:
        monkeypatch.setattr(
            loop,
            "_default_executor",
            pool if kind == "closed" else (None if kind == "missing" else object()),
        )
        with pytest.raises(ValueError, match="Notification fixture host executor is unavailable"):
            module.capture_host_executor()
    finally:
        monkeypatch.setattr(loop, "_default_executor", original)
        pool.shutdown(wait=True, cancel_futures=True)
