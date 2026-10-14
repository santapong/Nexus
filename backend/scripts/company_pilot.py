"""Explicit disposable owner-UAT operator CLI; no default worker/provider/remote action."""

import argparse
import asyncio
import getpass
import json
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.company.pilot_actions import populate_proposals
from nexus.company.pilot_bootstrap import bootstrap_directory, bootstrap_sources
from nexus.company.pilot_composition import compose_pilot, pilot_app
from nexus.company.pilot_config import PilotConfig
from nexus.company.pilot_governance import populate_governance
from nexus.company.pilot_plan import populate_plan
from nexus.company.pilot_setup import initialize_task, private_bytes
from nexus.settings import settings


def config_at(root: Path) -> PilotConfig:
    config = PilotConfig.model_validate_json(private_bytes(root / "config.json"))
    settings.jwt_secret_key = json.loads(private_bytes(root / "signer.json"))["jwt_secret_key"]
    settings.jwt_algorithm = "HS256"
    return config


def migrate_owned() -> None:
    from alembic.config import Config

    from alembic import command

    settings.company_database_url = "postgresql+asyncpg://santapong@/nexus_company_test_owner_uat?host=/tmp/nexus-release-tests-2026-10-13/socket&port=55438"
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "company_alembic")
    )
    command.upgrade(config, "head")
    asyncio.run(grant_app())


async def grant_app() -> None:
    from sqlalchemy import text

    engine = create_async_engine(settings.company_database_url)
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
        services = compose_pilot(factory, config)
        await bootstrap_directory(services, config)
        await bootstrap_sources(factory, config)
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
    parser.add_argument("mode", choices=["init", "bootstrap", "execute-report", "serve"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sdk-receipt", type=Path)
    parser.add_argument("--prompt-password", action="store_true")
    args = parser.parse_args()
    if args.mode == "init":
        if args.sdk_receipt is None:
            parser.error("--sdk-receipt required for explicit initialization")
        initialize_task(
            args.root,
            args.sdk_receipt,
            getpass.getpass("Disposable UAT owner password: ") if args.prompt_password else None,
        )
        sys.stdout.write(
            json.dumps({"task_directory": str(args.root), "credentials_are_private": True}) + "\n"
        )
        return
    config = config_at(args.root)
    if args.mode == "bootstrap":
        migrate_owned()
        asyncio.run(bootstrap(config))
        return
    if args.mode == "execute-report":
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
