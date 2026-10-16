"""Explicit disposable owner-UAT operator CLI; no default worker/provider/remote action."""

import argparse
import asyncio
import getpass
import json
import signal
import sys
from pathlib import Path

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.company.pilot_actions import populate_proposals
from nexus.company.pilot_bootstrap import bootstrap_directory, bootstrap_sources
from nexus.company.pilot_composition import compose_pilot, pilot_app
from nexus.company.pilot_config import PREVIEW_PROFILE, PilotConfig
from nexus.company.pilot_governance import populate_governance
from nexus.company.pilot_plan import populate_plan
from nexus.company.pilot_preview import create_preview_database, publish_preview_mandate
from nexus.company.pilot_setup import initialize_task, private_bytes
from nexus.settings import settings


def qualification_mode(args: argparse.Namespace) -> None:
    """Explicit existing-company mode; never read disposable account/signer roots."""
    from dbos import DBOS

    from nexus.builder.contained_query import clock_us
    from nexus.company.control_store import CompanyControls
    from nexus.company.directory_store import PersistentCompanyDirectory
    from nexus.company.services import CompanyServices
    from nexus.company_app import create_company_app
    from nexus.execution.qualification_application import (
        FiniteWorkerCredential,
        company_database_url,
        compose_qualification_api,
        compose_qualification_worker,
        drain_qualification_api,
        drain_qualification_worker,
        preflight_qualification_database,
        preflight_qualification_worker,
        read_secret_fd,
        require_admin_database,
        start_qualification_worker,
    )
    from nexus.execution.qualification_application_config import load_qualification_config
    from nexus.harness.journal import CompanyJournal

    end = clock_us() + 30_000_000
    frozen = load_qualification_config(
        args.qualification_config, args.qualification_config_sha, end_us=end
    )
    url = company_database_url(settings)
    if args.mode == "qualification-migrate":
        secret = read_secret_fd(args.admin_database_fd, limit=4096, end_us=end)
        admin = require_admin_database(secret.get_secret_value(), url)
        frozen.require_current(end_us=end)
        # Explicit operator/admin identity; restricted app never receives migration rights.
        DBOS.migrate(
            admin.render_as_string(hide_password=False), application_role="nexus_company_app"
        )
        return
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    if args.mode == "qualification-api":
        import uvicorn
        from litestar.config.cors import CORSConfig

        asyncio.run(preflight_qualification_database(factory, end_us=end))
        frozen.require_current(end_us=end)
        api = compose_qualification_api(factory, frozen.value)
        app = create_company_app(
            CompanyServices(
                PersistentCompanyDirectory(factory),
                CompanyJournal(factory),
                CompanyControls(factory),
            ),
            qualification_services=api,
            cors_config=CORSConfig(
                allow_origins=["http://127.0.0.1:5188", "http://localhost:5188"],
                allow_methods=["GET", "POST"],
                allow_headers=["Authorization", "Content-Type"],
            ),
        )

        async def shutdown() -> None:
            await drain_qualification_api(api)
            await engine.dispose()

        app.on_shutdown.append(shutdown)
        uvicorn.run(app, host=args.host, port=args.port, access_log=False, log_level="warning")
        return
    original = read_secret_fd(args.worker_credential_fd, limit=16384, end_us=end)
    worker = compose_qualification_worker(
        factory,
        frozen.value,
        settings,
        FiniteWorkerCredential(original),
        SecretStr(settings.jwt_secret_key),
    )

    async def run_worker() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()

        def stopping() -> None:
            worker.request_stop()
            stop.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stopping)
        launched = False
        try:
            await preflight_qualification_worker(worker, frozen.value, end_us=end)
            frozen.require_current(end_us=end)
            await start_qualification_worker(
                worker,
                url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
            )
            launched = True
            await stop.wait()
        finally:
            if worker.pending_owners():
                sys.stderr.write('{"status":"shutdown_pending_actual_resources"}\n')
                sys.stderr.flush()

            async def no_destroy() -> None:
                return None

            retirement = asyncio.create_task(
                drain_qualification_worker(worker, destroy=None if launched else no_destroy)
            )
            while not retirement.done():
                try:
                    await asyncio.shield(retirement)
                except asyncio.CancelledError:
                    continue
            retirement.result()
            await engine.dispose()

    asyncio.run(run_worker())


def config_at(root: Path) -> PilotConfig:
    config = PilotConfig.model_validate_json(private_bytes(root / "config.json"))
    settings.jwt_secret_key = json.loads(private_bytes(root / "signer.json"))["jwt_secret_key"]
    settings.jwt_algorithm = "HS256"
    return config


def migrate_owned(pilot: PilotConfig) -> None:
    from alembic.config import Config

    from alembic import command

    if pilot.profile == PREVIEW_PROFILE:
        create_preview_database(pilot)
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "company_alembic")
    )
    config.set_main_option("sqlalchemy.url", pilot.admin_database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    asyncio.run(grant_app(pilot.admin_database_url))


async def grant_app(database_url: str) -> None:
    from sqlalchemy import text

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public "
                    "TO nexus_company_app"
                )
            )
            await connection.execute(
                text("REVOKE DELETE ON ALL TABLES IN SCHEMA public FROM nexus_company_app")
            )
    finally:
        await engine.dispose()


async def bootstrap(config: PilotConfig) -> None:
    engine = create_async_engine(config.database_url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        services = await asyncio.to_thread(compose_pilot, factory, config)
        await bootstrap_directory(services, config)
        await bootstrap_sources(factory, config)
        if config.profile == PREVIEW_PROFILE:
            preview_mandate = await publish_preview_mandate(services.management.controls, config)
            sys.stdout.write(
                json.dumps(
                    {
                        "scope": config.profile,
                        "company_id": str(config.company_id),
                        "api": "http://127.0.0.1:9188",
                        "credential_file": str(
                            config.account_file.parent / "browser-credentials.json"
                        ),
                        "mandate": preview_mandate.model_dump(mode="json"),
                        "providers": False,
                        "queue": False,
                        "builder": False,
                    }
                )
                + "\n"
            )
            return
        mandate, charters, goal = await populate_governance(services, config)
        revision, payload = await populate_plan(services, config, mandate, charters, goal)
        await populate_proposals(factory, services, config, revision, payload)
        sys.stdout.write(
            json.dumps(
                {
                    "scope": config.profile,
                    "company_id": str(config.company_id),
                    "api": "http://127.0.0.1:9188",
                    "credential_file": str(config.account_file.parent / "browser-credentials.json"),
                }
            )
            + "\n"
        )
    finally:
        await engine.dispose()


async def run_report(config: PilotConfig) -> None:
    from nexus.company.pilot_execution import execute_report

    engine = create_async_engine(config.database_url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        receipt = await execute_report(factory, compose_pilot(factory, config), config)
        sys.stdout.write(
            json.dumps(
                {
                    "scope": config.profile,
                    "receipt_id": str(receipt.receipt_id),
                    "outcome": receipt.outcome,
                    "billing": "unknown",
                    "independent_acceptance": False,
                }
            )
            + "\n"
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=[
            "init",
            "bootstrap",
            "execute-report",
            "serve",
            "qualification-api",
            "qualification-worker",
            "qualification-migrate",
        ],
    )
    parser.add_argument("--root", type=Path)
    parser.add_argument("--qualification-config", type=Path)
    parser.add_argument("--qualification-config-sha")
    parser.add_argument("--worker-credential-fd", type=int)
    parser.add_argument("--admin-database-fd", type=int)
    parser.add_argument("--host", choices=["127.0.0.1", "::1"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9188)
    parser.add_argument("--sdk-receipt", type=Path)
    parser.add_argument("--prompt-password", action="store_true")
    parser.add_argument(
        "--profile",
        choices=["disposable-supervised-owner-uat-v1", PREVIEW_PROFILE],
        default="disposable-supervised-owner-uat-v1",
    )
    parser.add_argument("--database-name")
    parser.add_argument("--docs-manifest", type=Path)
    parser.add_argument("--docs-manifest-sha")
    args = parser.parse_args()
    if args.mode in {"qualification-api", "qualification-worker", "qualification-migrate"}:
        if (
            args.root is not None
            or args.qualification_config is None
            or args.qualification_config_sha is None
            or not 1024 <= args.port <= 65535
        ):
            parser.error(
                "Generic qualification needs exact config pins, local port and no disposable root"
            )
        if args.mode == "qualification-worker" and args.worker_credential_fd is None:
            parser.error("Explicit inherited worker credential descriptor is required")
        if args.mode == "qualification-migrate" and args.admin_database_fd is None:
            parser.error("Explicit inherited migration administrator descriptor is required")
        if (args.worker_credential_fd is not None and args.mode != "qualification-worker") or (
            args.admin_database_fd is not None and args.mode != "qualification-migrate"
        ):
            parser.error("Credential and administrator descriptors belong only to their exact mode")
        try:
            qualification_mode(args)
        except Exception as error:
            sys.stderr.write(
                json.dumps(
                    {"status": "qualification_startup_failed", "error_type": type(error).__name__}
                )
                + "\n"
            )
            raise SystemExit(1) from None
        return
    if (
        args.root is None
        or args.qualification_config is not None
        or args.qualification_config_sha is not None
        or args.worker_credential_fd is not None
        or args.admin_database_fd is not None
    ):
        parser.error(
            "Disposable pilot requires its root and does not implicitly enable qualification"
        )
    if args.mode == "init":
        if args.profile != PREVIEW_PROFILE and args.sdk_receipt is None:
            parser.error("--sdk-receipt required for explicit initialization")
        initialize_task(
            args.root,
            args.sdk_receipt,
            getpass.getpass("Disposable UAT owner password: ") if args.prompt_password else None,
            profile=args.profile,
            database_name=args.database_name,
            docs_manifest=args.docs_manifest,
            docs_manifest_sha256=args.docs_manifest_sha,
        )
        sys.stdout.write(
            json.dumps({"task_directory": str(args.root), "credentials_are_private": True}) + "\n"
        )
        return
    config = config_at(args.root)
    if args.mode == "bootstrap":
        migrate_owned(config)
        asyncio.run(bootstrap(config))
        return
    if args.mode == "execute-report":
        if config.profile == PREVIEW_PROFILE:
            parser.error("Local owner preview has no execution profile")
        asyncio.run(run_report(config))
        return
    import uvicorn

    engine = create_async_engine(config.database_url)
    services = compose_pilot(async_sessionmaker(engine, expire_on_commit=False), config)
    uvicorn.run(
        pilot_app(services), host="127.0.0.1", port=9188, access_log=False, log_level="warning"
    )


if __name__ == "__main__":
    main()
