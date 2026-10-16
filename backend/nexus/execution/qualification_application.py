"""Explicit qualification application composition; never goal/approval/provider bootstrap."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal, cast
from uuid import uuid4, uuid5

from dbos import DBOS
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contained_query import clock_us
from nexus.company.access import CompanyControlScope
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.worker_identity import (
    NotificationWorkerIdentities,
    OpaqueCredentialProvider,
)
from nexus.core.llm.company_endpoints import ServerEndpointBinding, SettingsEndpointResolver
from nexus.core.llm.qualification_contracts import QUEUE, capture_sdk_pins
from nexus.execution.effect_store import EffectStore
from nexus.execution.qualification_application_config import (
    NO_PROVIDER_VERSIONS,
    QualificationApplicationConfig,
    current,
    read_owned_fd,
)
from nexus.execution.qualification_dispatch import (
    REGISTRATION,
    QualificationApiServices,
    QualificationDispatchService,
)
from nexus.execution.qualification_reads import (
    QualificationReader,
    require_current_recipe_locked,
    require_qualification_work,
)
from nexus.execution.qualification_service import QualificationPreparationService
from nexus.execution.qualification_worker import (
    configure_qualification_worker,
    launch_qualification_worker,
)
from nexus.execution.qualification_worker_services import QualificationWorkerServices
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import db_now
from nexus.harness.qualification_evidence import FileQualificationEvidenceStore
from nexus.settings import Settings


@dataclass(frozen=True)
class FiniteWorkerCredential:
    """Original genuine session only; verifier preserves its actual iat/exp each time."""

    token: SecretStr = field(repr=False)

    async def credential(self) -> SecretStr:
        return self.token


def read_secret_fd(fd: int, *, limit: int, end_us: int) -> SecretStr:
    raw, _ = read_owned_fd(fd, limit, end_us=end_us)
    try:
        value = raw.decode("utf-8")
    except UnicodeError:
        raise ValueError("Qualification credential descriptor is unavailable") from None
    if not value or value.strip() != value or "\x00" in value:
        raise ValueError("Qualification credential descriptor is unavailable")
    current(end_us)
    return SecretStr(value)


def company_database_url(settings: Settings) -> URL:
    """Dedicated explicitly configured company database, no legacy/default fallback."""
    if not settings.company_database_url:
        raise ValueError("Dedicated qualification company database is unavailable")
    url = make_url(settings.company_database_url)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.username != "nexus_company_app"
        or not url.database
    ):
        raise ValueError("Qualification requires its explicit restricted company database")
    return url


def require_admin_database(value: str, app: URL) -> URL:
    admin = make_url(value)
    if (
        admin.drivername != "postgresql+psycopg"
        or not admin.username
        or admin.username == app.username
        or (admin.host, admin.port, admin.database, dict(admin.query))
        != (app.host, app.port, app.database, dict(app.query))
    ):
        raise ValueError("Explicit migration administrator must bind the same company database")
    return admin


def compose_qualification_api(
    factory: async_sessionmaker[AsyncSession], config: QualificationApplicationConfig
) -> QualificationApiServices:
    config = QualificationApplicationConfig.model_validate_json(
        config.model_dump_json(by_alias=True)
    )
    preparation = QualificationPreparationService(
        factory, config.recipes, allocation_usd=config.allocation_usd
    )
    return QualificationApiServices(
        preparation,
        QualificationDispatchService(preparation, ExecutionStore(factory)),
        QualificationReader(preparation, FileQualificationEvidenceStore(config.evidence_root)),
    )


def compose_qualification_worker(
    factory: async_sessionmaker[AsyncSession],
    config: QualificationApplicationConfig,
    settings: Settings,
    credentials: OpaqueCredentialProvider,
    signing_key: SecretStr,
) -> QualificationWorkerServices:
    if (
        settings.jwt_algorithm != "HS256"
        or signing_key.get_secret_value() != settings.jwt_secret_key
    ):
        raise ValueError("Qualification worker must use the configured HTTP signer")
    api = compose_qualification_api(factory, config)
    bindings: dict[str, ServerEndpointBinding] = {}
    for recipe in config.recipes:
        row = recipe.target
        binding = ServerEndpointBinding(
            row.endpoint_id,
            row.provider,
            row.api_family,
            "https://api.openai.com/v1"
            if row.provider == "openai"
            else "https://generativelanguage.googleapis.com",
            30,
        )
        if binding.endpoint_id in bindings and bindings[binding.endpoint_id] != binding:
            raise ValueError("Qualification endpoint ID has conflicting server bindings")
        bindings[binding.endpoint_id] = binding
    return QualificationWorkerServices(
        factory,
        ExecutionStore(factory),
        EffectStore(factory),
        api.preparation,
        NotificationWorkerIdentities(credentials, signing_key, enabled=True),
        SettingsEndpointResolver(settings, tuple(bindings.values())),
        FileQualificationEvidenceStore(config.evidence_root),
        config.worker_id,
        REGISTRATION,
    )


async def preflight_qualification_worker(
    services: QualificationWorkerServices, config: QualificationApplicationConfig, *, end_us: int
) -> None:
    """Read-only current native/configured preconditions; no key/SDK client or Work creation."""
    current(end_us)
    services.require_composition()
    witness = await services.identities.current()
    if (witness.identity.principal_id, witness.identity.workspace_id) != (
        config.owner_id,
        config.workspace_id,
    ):
        raise ValueError("Qualification worker credential differs from configured owner")
    current(end_us)
    task = asyncio.create_task(capture_sdk_pins())
    services._startup_owners.append(cast(asyncio.Task[object], task))
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    try:
        async with asyncio.timeout(max(0, end_us - clock_us()) / 1_000_000):
            actual = await asyncio.shield(task)
    except BaseException as error:
        error.__dict__["_nexus_qualification_pending"] = services.pending_owners()
        raise
    if any(row.sdk_pins != actual for row in config.recipes):
        raise ValueError("Qualification configured SDK sources differ from installed source")
    current(end_us)
    await preflight_qualification_database(services.factory, end_us=end_us)
    scope = CompanyControlScope(
        company_id=config.goal.company_id,
        principal_id=witness.identity.principal_id,
        operation_id=uuid4(),
        trace_id=uuid4(),
    )
    async with management_owner_transaction(services.factory, scope, witness.identity) as (
        session,
        control,
        _,
    ):
        if control.price_version in NO_PROVIDER_VERSIONS:
            raise ValueError("No-provider company profile cannot enable qualification")
        existing = await session.get(
            ExecutionWork,
            (
                config.goal.company_id,
                uuid5(config.goal.goal_id, "nexus:model-qualification:task:v1"),
            ),
        )
        if existing is not None:
            require_qualification_work(services.preparation, existing, config.recipes[0])
            if (existing.actor_id, existing.workspace_id) != (config.owner_id, config.workspace_id):
                raise ValueError("Qualification existing root belongs to another original identity")
        for recipe in config.recipes:
            current(end_us)
            await require_current_recipe_locked(
                services.preparation, session, control, scope, witness.identity, recipe
            )
        witness.require_time(await db_now(session))
    for endpoint_id in dict.fromkeys(row.target.endpoint_id for row in config.recipes):
        current(end_us)
        await services.resolver.resolve(
            endpoint_id
        )  # Validate availability; never cache/disclose key.
    if await services.identities.current() != witness:
        raise ValueError("Qualification startup credential changed instead of retaining its window")
    services.require_composition()
    current(end_us)


async def preflight_qualification_database(
    factory: async_sessionmaker[AsyncSession],
    *,
    end_us: int,
    schema_versions: tuple[Literal["company_016", "company_017"], ...] = ("company_016",),
) -> None:
    if (
        not schema_versions
        or len(set(schema_versions)) != len(schema_versions)
        or not set(schema_versions) <= {"company_016", "company_017"}
    ):
        raise ValueError("Explicit supported company schema is unavailable")
    current(end_us)
    async with asyncio.timeout(max(0, end_us - clock_us()) / 1_000_000), factory() as session:
        if (
            await session.scalar(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
            )
            is not False
        ):
            raise ValueError("Qualification requires actual restricted role")
        current(end_us)
        if (
            await session.scalar(text("SELECT version_num FROM company_alembic_version"))
            not in schema_versions
        ):
            raise ValueError(
                "Qualification requires normal company016"
                if schema_versions == ("company_016",)
                else "Qualification requires its explicit normal company schema"
            )
        for name in ("fsync", "synchronous_commit", "full_page_writes"):
            current(end_us)
            if await session.scalar(text(f"SHOW {name}")) != "on":
                raise ValueError("Qualification requires durable native accounting")
    current(end_us)


async def start_qualification_worker(
    services: QualificationWorkerServices, system_database_url: str
) -> None:
    services.require_accepting()
    configure_qualification_worker(services, system_database_url)
    try:
        DBOS.listen_queues([QUEUE])
        await launch_qualification_worker()
    except BaseException as first:
        # Configure owns the runtime even if launch/queue registration only partially
        # succeeds. Retain the real retirement task through repeated caller stops.
        retirement = asyncio.create_task(drain_qualification_worker(services))
        while not retirement.done():
            try:
                await asyncio.shield(retirement)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        try:
            retirement.result()
        except BaseException as secondary:
            first.__dict__["_nexus_qualification_secondary"] = type(secondary).__name__
        raise first


async def drain_qualification_worker(
    services: QualificationWorkerServices, *, destroy: Callable[[], Awaitable[None]] | None = None
) -> None:
    """Resource completion only after stopping; original operation ends never change."""
    services.request_stop()
    while services.pending_owners() or any(
        op.running for op in tuple(services._operations.values())
    ):
        # Existing operations keep their real tasks and original clocks; this wait
        # cannot adopt a model result or launch another native operation.
        await asyncio.sleep(0.05)
    if destroy is not None:
        await destroy()
    else:
        await asyncio.to_thread(DBOS.destroy, workflow_completion_timeout_sec=1)


async def drain_qualification_api(services: QualificationApiServices) -> None:
    """ASGI has stopped intake; retain actual staging/file leaves before engine disposal."""
    while services.dispatch.pending_owners() or (
        services.reads.evidence is not None and services.reads.evidence.pending_owners()
    ):
        await asyncio.sleep(0.05)
