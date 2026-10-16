"""Planning resource/startup composition; no DBOS construction, SQL or network effects."""

import asyncio
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.planning_native_facts import read_end
from nexus.execution.planning_application import PlanningApplication, compose_planning_application
from nexus.execution.planning_application_runtime import (
    capture_planning_worker_runtime,
    drain_planning_application,
    retire_planning_application,
    start_planning_application_worker,
)
from nexus.execution.planning_services import PlanningOperation
from nexus.tests.unit.planning_application_fixture import configuration
from nexus.tests.unit.test_planning_application import (
    TEST_SIGNER,
    SuppliedCredential,
    application_settings,
)


def application(root: Path) -> PlanningApplication:
    return compose_planning_application(
        async_sessionmaker[AsyncSession](),
        configuration(root),
        application_settings(),
        SuppliedCredential(),
        SecretStr(TEST_SIGNER),
    )


async def pending_operation(
    app: PlanningApplication,
    entered: asyncio.Event,
    finish: asyncio.Event,
    order: list[str],
) -> None:
    operation = PlanningOperation(app.runtime, "actual-resource-unit", read_end())

    async def leaf() -> None:
        entered.set()
        await finish.wait()
        order.append("leaf")

    try:
        await operation.call(leaf())
    except asyncio.CancelledError as error:
        operation.first = error
    await operation.retire()
    operation.finish()


async def test_shutdown_keeps_actual_leaf_and_running_operation_until_destroy_and_dispose(
    tmp_path: Path,
) -> None:
    app = application(tmp_path)
    entered, finish = asyncio.Event(), asyncio.Event()
    order: list[str] = []
    driver = asyncio.create_task(pending_operation(app, entered, finish, order))
    await entered.wait()
    destroy = AsyncMock(side_effect=lambda: order.append("destroy"))
    dispose = AsyncMock(side_effect=lambda: order.append("dispose"))
    retirement = asyncio.create_task(
        retire_planning_application(app, destroy=destroy, dispose=dispose)
    )
    await asyncio.sleep(0.01)
    assert app.lifecycle.pending_owners() and not destroy.called and not dispose.called
    for _ in range(3):
        retirement.cancel()
        await asyncio.sleep(0)
    assert not retirement.done() and app.runtime._stopping.is_set()
    with pytest.raises(ValueError, match="stopped"):
        app.runtime.require_accepting()
    finish.set()
    await driver
    await retirement
    assert order == ["leaf", "destroy", "dispose"]


async def test_cancelled_wrapper_is_not_resource_completion(tmp_path: Path) -> None:
    app = application(tmp_path)
    wrapper = asyncio.create_task(asyncio.sleep(100))
    wrapper.cancel()
    with pytest.raises(asyncio.CancelledError):
        await wrapper
    operation = PlanningOperation(app.runtime, "cancelled-wrapper-unit", read_end())
    operation.owners.append(wrapper)
    operation.running = False
    destroy = AsyncMock()
    draining = asyncio.create_task(drain_planning_application(app, destroy=destroy))
    await asyncio.sleep(0.01)
    assert not draining.done() and not destroy.called
    draining.cancel()
    with pytest.raises(asyncio.CancelledError):
        await draining


async def test_partial_worker_launch_retires_configured_fixed_runtime_preserving_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dbos import DBOS

    from nexus.execution import planning_application_runtime as module

    app = application(tmp_path)
    order: list[object] = []
    failure = ValueError("supplied launch failure")
    monkeypatch.setattr(
        module, "configure_planning_worker", lambda *args: order.append("configure")
    )
    monkeypatch.setattr(
        DBOS, "listen_queues", lambda queues: pytest.fail("The real launcher owns queue policy")
    )

    async def launch() -> None:
        order.append("launch")
        raise failure

    async def drain(
        actual: PlanningApplication,
        *,
        destroy: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        assert actual is app
        order.append("retire")

    monkeypatch.setattr(module, "launch_planning_worker", launch)
    monkeypatch.setattr(module, "drain_planning_application", drain)
    with pytest.raises(ValueError) as caught:
        await start_planning_application_worker(app, "unused-unit-url")
    assert caught.value is failure
    assert order == ["configure", "launch", "retire"]


async def test_actual_host_executor_survives_sdk_adoption_and_repeated_destroy_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dbos import DBOS

    await asyncio.to_thread(lambda: None)
    loop = asyncio.get_running_loop()
    original = getattr(loop, "_default_executor", None)
    assert isinstance(original, ThreadPoolExecutor)
    host = ThreadPoolExecutor(max_workers=1, thread_name_prefix="planning-unit-host")
    sdk = ThreadPoolExecutor(max_workers=1, thread_name_prefix="planning-unit-sdk")
    entered, finish = threading.Event(), threading.Event()
    calls: list[str] = []

    def destroy(*, workflow_completion_timeout_sec: int) -> None:
        assert workflow_completion_timeout_sec == 1
        calls.append(threading.current_thread().name)
        entered.set()
        assert finish.wait(5)
        sdk.shutdown(wait=False, cancel_futures=True)

    monkeypatch.setattr(DBOS, "destroy", destroy)
    try:
        loop.set_default_executor(host)
        runtime = await capture_planning_worker_runtime(application(tmp_path))
        loop.set_default_executor(sdk)
        retirement = asyncio.create_task(runtime.destroy())
        async with asyncio.timeout(2):
            while not entered.is_set():
                await asyncio.sleep(0)
        for _ in range(3):
            retirement.cancel()
            await asyncio.sleep(0)
        assert not retirement.done() and runtime.pending_owners()
        finish.set()
        await retirement
        assert not runtime.pending_owners()
        assert getattr(loop, "_default_executor", None) is host
        assert (await asyncio.to_thread(lambda: threading.current_thread().name)).startswith(
            "planning-unit-host"
        )
        await runtime.destroy()
        assert len(calls) == 1 and calls[0].startswith("planning-unit-host")
    finally:
        finish.set()
        loop.set_default_executor(original)
        host.shutdown(wait=True, cancel_futures=True)
        sdk.shutdown(wait=True, cancel_futures=True)


async def test_partial_launch_restores_exact_host_pool_after_actual_teardown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dbos import DBOS

    from nexus.execution import planning_application_runtime as module

    await asyncio.to_thread(lambda: None)
    loop = asyncio.get_running_loop()
    host = getattr(loop, "_default_executor", None)
    assert isinstance(host, ThreadPoolExecutor)
    sdk = ThreadPoolExecutor(max_workers=1, thread_name_prefix="partial-sdk")
    failure = ValueError("supplied partial launch failure")
    monkeypatch.setattr(module, "configure_planning_worker", lambda *args: None)
    monkeypatch.setattr(DBOS, "listen_queues", lambda queues: None)

    async def launch() -> None:
        loop.set_default_executor(sdk)
        raise failure

    def destroy(*, workflow_completion_timeout_sec: int) -> None:
        sdk.shutdown(wait=False, cancel_futures=True)

    monkeypatch.setattr(module, "launch_planning_worker", launch)
    monkeypatch.setattr(DBOS, "destroy", destroy)
    try:
        with pytest.raises(ValueError) as caught:
            await start_planning_application_worker(application(tmp_path), "unused-unit-url")
        assert caught.value is failure and getattr(loop, "_default_executor", None) is host
        assert await asyncio.to_thread(lambda: True)
    finally:
        assert isinstance(host, ThreadPoolExecutor)
        loop.set_default_executor(host)
        sdk.shutdown(wait=True, cancel_futures=True)


async def test_wrong_loop_and_closed_host_are_denied_without_sdk_teardown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from dbos import DBOS

    app = application(tmp_path)
    actual = await capture_planning_worker_runtime(app)
    foreign = asyncio.new_event_loop()
    closed = ThreadPoolExecutor(max_workers=1)
    closed.shutdown(wait=True)
    destroy = AsyncMock(side_effect=AssertionError("Mismatched owner invoked SDK teardown"))
    monkeypatch.setattr(DBOS, "destroy", destroy)
    try:
        with pytest.raises(ValueError, match="Original planning host"):
            await replace(actual, loop=foreign).destroy()
        actual.loop.set_default_executor(closed)
        with pytest.raises(ValueError, match="Original planning host"):
            await capture_planning_worker_runtime(app)
        destroy.assert_not_called()
    finally:
        actual.loop.set_default_executor(actual.executor)
        foreign.close()


async def test_real_launcher_composes_pinned_one_shot_listen_api_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the real launcher/listen API; only SDK state and SQL/effect leaves are supplied.

    The >50-line exception retains the complete real-call composition and bounded
    failure diagnostics together, rather than replacing the decisive launcher.
    """
    import json
    from dataclasses import dataclass

    import dbos._dbos as sdk_module
    from dbos import DBOS

    from nexus.execution import planning_application_runtime as runtime_module
    from nexus.execution import planning_worker as worker_module

    @dataclass
    class SuppliedSDKState:
        _launched: bool = False
        _listening_queues: list[str] | None = None

    app, state, events = application(tmp_path), SuppliedSDKState(), []
    assert vars(runtime_module)["launch_planning_worker"] is worker_module.launch_planning_worker
    monkeypatch.setattr(sdk_module, "_dbos_global_instance", state)
    monkeypatch.setattr(worker_module, "_services", app.runtime)
    sql = AsyncMock(return_value=False)
    register = AsyncMock()
    monkeypatch.setattr(AsyncSession, "scalar", sql)
    monkeypatch.setattr(DBOS, "register_queue_async", register)

    def configure(actual: object, url: str) -> None:
        assert actual is app.runtime and url == "unused-unit-url"
        events.append("configure")

    def launch() -> None:
        assert state._listening_queues == ["nexus.planning"]
        state._launched = True
        events.append("sdk.launch")

    def destroy(*, workflow_completion_timeout_sec: int) -> None:
        assert workflow_completion_timeout_sec == 1
        events.append("sdk.destroy")

    monkeypatch.setattr(runtime_module, "configure_planning_worker", configure)
    monkeypatch.setattr(DBOS, "launch", launch)
    monkeypatch.setattr(DBOS, "destroy", destroy)
    # DBOS.listen_queues is deliberately the unchanged installed SDK method.
    try:
        async with asyncio.timeout(5):
            owner = await start_planning_application_worker(app, "unused-unit-url")
    except BaseException as error:
        (tmp_path / "queue-composition-failure.json").write_text(
            json.dumps(
                {
                    "type": type(error).__name__,
                    "message": str(error),
                    "events": events,
                    "listening_queues": state._listening_queues,
                    "launched": state._launched,
                }
            )
        )
        raise
    assert events == ["configure", "sdk.launch"]
    assert state._listening_queues == ["nexus.planning"] and state._launched
    sql.assert_awaited_once()
    assert sql.await_args is not None
    assert "pg_roles" in str(sql.await_args.args[0])
    register.assert_awaited_once_with(
        "nexus.planning",
        global_concurrency=1,
        worker_concurrency=1,
        polling_interval_sec=1.0,
    )
    await owner.destroy()
    assert events == ["configure", "sdk.launch", "sdk.destroy"]
