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
from nexus.company.pilot_config import PREVIEW_PROFILE, PilotConfig
from nexus.company.pilot_governance import populate_governance
from nexus.company.pilot_plan import populate_plan
from nexus.company.pilot_preview import create_preview_database, publish_preview_mandate
from nexus.company.pilot_setup import initialize_task, private_bytes
from nexus.settings import settings


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
    parser.add_argument("mode", choices=["init", "bootstrap", "execute-report", "serve"])
    parser.add_argument("--root", type=Path, required=True)
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
