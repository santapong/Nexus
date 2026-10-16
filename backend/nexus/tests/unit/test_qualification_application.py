"""Opt-in composition/configuration; fake credentials and supplied DB leaves only.

The >400-line exception keeps the bounded FD/configuration and actual SDK-stop
ownership matrix adjacent, without introducing another fixture framework.
"""

import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import jwt
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
from nexus.execution.qualification_application import (
    FiniteWorkerCredential,
    compose_qualification_api,
    compose_qualification_worker,
    drain_qualification_worker,
    read_secret_fd,
)
from nexus.execution.qualification_application_config import (
    QualificationApplicationConfig,
    load_qualification_config,
)
from nexus.settings import Settings
from nexus.tests.unit.test_qualification_contracts import recipe

SIGNER = "synthetic-only-qualification-signer-at-least-32-characters"


def config(tmp_path: Path) -> QualificationApplicationConfig:
    chosen = recipe()
    return QualificationApplicationConfig(
        goal=chosen.goal,
        owner_id=UUID(int=3),
        workspace_id=UUID(int=2),
        worker_id=UUID(int=9),
        evidence_root=tmp_path / "evidence",
        recipes=(chosen,),
    )


def injected() -> Settings:
    return Settings(
        _env_file=None,
        openai_api_key="fake-openai-key",
        google_api_key="fake-google-key",
        jwt_secret_key=SIGNER,
        company_database_url="postgresql+asyncpg://nexus_company_app@/company_application?host=/tmp/mock-socket&port=55438",
    )


def token() -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(UUID(int=3)),
            "workspace_id": str(UUID(int=2)),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=10)).timestamp()),
        },
        SIGNER,
        algorithm="HS256",
    )


def test_explicit_composition_is_pure_and_retains_concrete_original_dependencies(
    tmp_path: Path,
) -> None:
    spec = config(tmp_path)
    factory = async_sessionmaker[AsyncSession]()
    api = compose_qualification_api(factory, spec)
    worker = compose_qualification_worker(
        factory, spec, injected(), FiniteWorkerCredential(SecretStr(token())), SecretStr(SIGNER)
    )
    assert api.preparation.factory is worker.factory is factory
    assert api.reads.evidence is not None and api.reads.evidence._root == spec.evidence_root
    assert isinstance(worker.identities, NotificationWorkerIdentities)
    assert not tmp_path.joinpath("evidence").exists()
    assert not worker.pending_owners()


@pytest.mark.parametrize("fault", ["goal", "unknown", "secret", "preview"])
def test_closed_config_cannot_rotate_goal_inject_authority_or_relabel_preview(
    tmp_path: Path, fault: str
) -> None:
    data = config(tmp_path).model_dump(mode="json")
    if fault == "goal":
        data["recipes"][0]["goal"]["revision_id"] = str(UUID(int=99))
    elif fault == "preview":
        data["recipes"][0]["target"]["price"]["version"] = "nexus-preview-no-provider-v1"
    else:
        data["actor_id" if fault == "unknown" else "api_key"] = "forbidden"
    with pytest.raises(ValueError):
        QualificationApplicationConfig.model_validate_json(__import__("json").dumps(data))


def test_owned_config_hash_permissions_and_final_fd_close_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.builder.contained_query import clock_us
    from nexus.execution import qualification_application_config as module

    tmp_path.chmod(0o700)
    path = tmp_path / "qualification.json"
    raw = config(tmp_path).model_dump_json(by_alias=True).encode()
    path.write_bytes(raw)
    path.chmod(0o600)
    digest = hashlib.sha256(raw).hexdigest()
    end = clock_us() + 1_000_000
    assert load_qualification_config(path, digest, end_us=end).value == config(tmp_path)
    with pytest.raises(ValueError):
        load_qualification_config(path, "f" * 64, end_us=end)
    path.chmod(0o644)
    with pytest.raises(ValueError):
        load_qualification_config(path, digest, end_us=end)
    path.chmod(0o600)
    real_close = os.close
    now = [1]

    def close(fd: int) -> None:
        real_close(fd)
        now[0] = 10

    monkeypatch.setattr(module, "clock_us", lambda: now[0])
    monkeypatch.setattr(os, "close", close)
    with pytest.raises(TimeoutError):
        load_qualification_config(path, digest, end_us=10)


async def test_actual_finite_jwt_from_owned_fd_is_not_renewed_or_exposed(tmp_path: Path) -> None:
    from nexus.builder.contained_query import clock_us

    path = tmp_path / "token"
    value = token()
    path.write_text(value)
    path.chmod(0o600)
    fd = os.open(path, os.O_RDONLY)
    credential = FiniteWorkerCredential(
        read_secret_fd(fd, limit=16384, end_us=clock_us() + 1_000_000)
    )
    with pytest.raises(OSError):
        os.fstat(fd)
    assert value not in repr(credential)
    verifier = NotificationWorkerIdentities(credential, SecretStr(SIGNER), enabled=True)
    first = await verifier.current()
    second = await verifier.current()
    assert first.expires_at == second.expires_at and first.issued_at == second.issued_at


async def test_shutdown_retains_actual_inflight_leaf_before_destroy_or_disposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.execution.qualification_worker_context import QualificationOperation

    spec = config(tmp_path)
    factory = async_sessionmaker[AsyncSession]()
    worker = compose_qualification_worker(
        factory, spec, injected(), FiniteWorkerCredential(SecretStr(token())), SecretStr(SIGNER)
    )
    entered, retire = asyncio.Event(), asyncio.Event()
    order = []

    async def operation() -> None:
        current = QualificationOperation(worker)
        worker._operations["actual"] = current

        async def leaf() -> None:
            entered.set()
            await retire.wait()
            order.append("leaf")

        try:
            await current.call(leaf())
        except asyncio.CancelledError as error:
            current.first = error
        await current.settle()
        current.running = False

    driver = asyncio.create_task(operation())
    await entered.wait()
    destroy = AsyncMock(side_effect=lambda: order.append("destroy"))
    draining = asyncio.create_task(drain_qualification_worker(worker, destroy=destroy))
    await asyncio.sleep(0)
    assert not draining.done() and not destroy.called
    assert worker.pending_owners() and not worker.pending_owners()[0].cancelled()
    with pytest.raises(ValueError):
        QualificationOperation(worker)
    retire.set()
    await driver
    await draining
    assert order == ["leaf", "destroy"]


async def test_start_orders_fixed_queue_before_launch_and_stopped_worker_cannot_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dbos import DBOS

    from nexus.execution import qualification_application as module

    spec = config(tmp_path)
    factory = async_sessionmaker[AsyncSession]()
    worker = compose_qualification_worker(
        factory, spec, injected(), FiniteWorkerCredential(SecretStr(token())), SecretStr(SIGNER)
    )
    order: list[object] = []
    monkeypatch.setattr(
        module, "configure_qualification_worker", lambda *args: order.append("configure")
    )
    monkeypatch.setattr(DBOS, "listen_queues", lambda queues: order.append(tuple(queues)))

    async def launch() -> None:
        order.append("launch")

    monkeypatch.setattr(module, "launch_qualification_worker", launch)
    await module.start_qualification_worker(worker, "unused-unit-url")
    assert order == ["configure", ("nexus.model-qualification",), "launch"]
    worker.request_stop()
    with pytest.raises(ValueError):
        await module.start_qualification_worker(worker, "unused-unit-url")
    assert len(order) == 3


async def test_preflight_native_no_provider_denies_before_any_quote_work_or_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from typing import cast

    from nexus.builder.contained_query import clock_us
    from nexus.execution import qualification_application as module
    from nexus.harness.journal_models import CompanyControl

    spec = config(tmp_path)
    factory = async_sessionmaker[AsyncSession]()
    worker = compose_qualification_worker(
        factory, spec, injected(), FiniteWorkerCredential(SecretStr(token())), SecretStr(SIGNER)
    )
    monkeypatch.setattr(
        module, "capture_sdk_pins", AsyncMock(return_value=spec.recipes[0].sdk_pins)
    )
    monkeypatch.setattr(module, "preflight_qualification_database", AsyncMock())

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
        yield (
            cast(AsyncSession, object()),
            CompanyControl(price_version="nexus-preview-no-provider-v1"),
            datetime.now(UTC),
        )

    monkeypatch.setattr(module, "management_owner_transaction", transaction)
    quote = AsyncMock()
    monkeypatch.setattr(module, "require_current_recipe_locked", quote)
    with pytest.raises(ValueError, match="No-provider"):
        await module.preflight_qualification_worker(worker, spec, end_us=clock_us() + 1_000_000)
    quote.assert_not_awaited()
    assert not worker.pending_owners() and not worker._operations


async def test_actual_client_stop_keeps_sdk_and_receipt_owners_and_never_reports_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    import httpx2

    from nexus.core.llm.company_adapter_contracts import ServerEndpoint
    from nexus.execution import qualification_worker as module
    from nexus.execution.qualification_worker_context import (
        QualificationContext,
        QualificationOperation,
    )
    from nexus.tests.unit.test_company_provider_conformance import response
    from nexus.tests.unit.test_qualification_client import prepared
    from nexus.tests.unit.test_qualification_worker import services

    value, context = services(tmp_path, monkeypatch)
    (tmp_path / "actual").mkdir(mode=0o700)
    client, order = prepared(tmp_path / "actual", monkeypatch)
    entered, retire = asyncio.Event(), asyncio.Event()

    async def wire(request: httpx2.Request) -> httpx2.Response:
        order.append("actual-post")
        entered.set()
        await retire.wait()
        body = response("openai")
        body["model"] = client._recipe.target.model_id
        return httpx2.Response(200, json=body)

    original = client._resolver.resolve

    async def endpoint(endpoint_id: str) -> ServerEndpoint:
        return replace(await original(endpoint_id), transport=httpx2.MockTransport(wire))

    monkeypatch.setattr(client._resolver, "resolve", endpoint)
    monkeypatch.setattr(module, "read_context", AsyncMock(return_value=context))

    async def acquire(op: QualificationOperation, ctx: QualificationContext) -> int:
        op.lease = client._lease
        op.identity = ctx.credential.identity
        return op.end - 5_000_000

    monkeypatch.setattr(module, "acquire_context", acquire)
    monkeypatch.setattr(module, "refresh_issued", AsyncMock(return_value=None))
    monkeypatch.setattr(module, "QualificationClient", lambda *args, **kwargs: client)

    async def release(*args: object, **kwargs: object) -> object:
        assert not client.pending_owners()
        order.append("release")
        return object()

    monkeypatch.setattr(value.execution, "release", release)
    driver = asyncio.create_task(
        module.execute_qualification_segment(
            value, context.command, workflow_id=context.command.workflow_id
        )
    )
    await entered.wait()
    destroy = AsyncMock()
    draining = asyncio.create_task(drain_qualification_worker(value, destroy=destroy))
    await asyncio.sleep(0.02)
    assert not driver.done() and not destroy.called and value.pending_owners()
    retire.set()
    with pytest.raises(asyncio.CancelledError) as stopped:
        await driver
    await draining
    result = vars(stopped.value)["_nexus_qualification_segment"]
    assert result.status == "outcome_unknown" and result.error_type == "CancelledError"
    assert order == ["intent", "actual-post", "receipt", "release"]
    assert not value.pending_owners() and destroy.await_count == 1


def test_original_descriptor_failure_is_not_overwritten_by_close_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.execution import qualification_application_config as module

    path = tmp_path / "private"
    path.write_bytes(b"synthetic-only")
    path.chmod(0o600)
    fd = os.open(path, os.O_RDONLY)
    original = TimeoutError("original deadline")
    real_close = os.close

    def expired(_: int) -> None:
        raise original

    def close(descriptor: int) -> None:
        real_close(descriptor)
        raise OSError("supplied close failure")

    monkeypatch.setattr(module, "current", expired)
    monkeypatch.setattr(os, "close", close)
    with pytest.raises(TimeoutError) as caught:
        read_secret_fd(fd, limit=16384, end_us=10)
    assert caught.value is original
    assert vars(original)["_nexus_qualification_secondary"] == "OSError"


def test_new_owned_data_child_does_not_rebind_unchanged_operator_configuration(
    tmp_path: Path,
) -> None:
    from nexus.builder.contained_query import clock_us

    tmp_path.chmod(0o700)
    path = tmp_path / "application.json"
    raw = config(tmp_path).model_dump_json(by_alias=True).encode()
    path.write_bytes(raw)
    path.chmod(0o600)
    end = clock_us() + 1_000_000
    original = load_qualification_config(path, hashlib.sha256(raw).hexdigest(), end_us=end)
    (tmp_path / "evidence").mkdir(mode=0o700)
    original.require_current(end_us=end)


async def test_partial_launch_still_retires_its_configured_runtime_and_preserves_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dbos import DBOS

    from nexus.execution import qualification_application as module

    worker = compose_qualification_worker(
        async_sessionmaker[AsyncSession](),
        config(tmp_path),
        injected(),
        FiniteWorkerCredential(SecretStr(token())),
        SecretStr(SIGNER),
    )
    original = ValueError("actual launch failure")
    order = []
    monkeypatch.setattr(
        module, "configure_qualification_worker", lambda *args: order.append("configure")
    )
    monkeypatch.setattr(DBOS, "listen_queues", lambda queues: order.append("listen"))

    async def launch() -> None:
        order.append("launch")
        raise original

    async def retire(actual: object) -> None:
        assert actual is worker
        order.append("retire")

    monkeypatch.setattr(module, "launch_qualification_worker", launch)
    monkeypatch.setattr(module, "drain_qualification_worker", retire)
    with pytest.raises(ValueError) as caught:
        await module.start_qualification_worker(worker, "unused-unit-url")
    assert caught.value is original and order == ["configure", "listen", "launch", "retire"]
