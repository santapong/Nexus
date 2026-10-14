"""Prepare one exact process fixture; worker launch requires separate review."""

import asyncio
import json
from hashlib import sha256
from pathlib import Path

from dbos import DBOS
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.settings import settings
from nexus.tests.engineering_fixture import engineering_scenario
from nexus.tests.engineering_process_config import process_config
from nexus.tests.engineering_process_prepare import enqueue_pending_verifier
from nexus.tests.engineering_process_scope import PROCESS_ROOTS, require_process_root
from nexus.tests.integration.test_company_directory import migrate

ALLOWED_PROCESS_DATABASES = frozenset(PROCESS_ROOTS)


async def prepare_case(root: Path) -> None:
    """Only the reviewed new task root and exact database are eligible for first preparation."""
    url = make_url(settings.company_test_database_url)
    assert url.database in ALLOWED_PROCESS_DATABASES and url.username == "santapong"
    assert isinstance(url.database, str)
    require_process_root(url.database, root, existing=False)
    root.mkdir(mode=0o700)
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    try:
        async with admin.begin() as connection:
            assert not await connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema IN ('public','dbos')"
                )
            )
            await connection.run_sync(migrate, "upgrade")
        await asyncio.to_thread(
            DBOS.migrate,
            url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
            application_role="nexus_company_app",
        )
        item = await engineering_scenario(
            async_sessionmaker(app, expire_on_commit=False),
            root,
            reserve_native_dispatch=False,
            defer_verifier=True,
        )
        command = await enqueue_pending_verifier(item)
        config = process_config(item, command, url.database, root)
        raw = config.model_dump_json().encode()
        (root / "engineering-process-config.json").write_bytes(raw)
        (root / "engineering-command.json").write_text(command.model_dump_json())
        packet = {
            "database": url.database,
            "root": str(root),
            "command": command.model_dump(mode="json"),
            "config_sha256": sha256(raw).hexdigest(),
            "spec_sha256": sha256(config.verifier_spec.model_dump_json().encode()).hexdigest(),
            "source": config.verifier_spec.job.source.model_dump(mode="json"),
            "image_id": config.image_id,
            "state": "prepared actualpendingauthorized+atomicnativeDBOSenqueue; workerUNLAUNCHED",
        }
        (root / "launch-review-packet.json").write_text(json.dumps(packet, indent=2) + "\n")
    finally:
        await app.dispose()
        await admin.dispose()


if __name__ == "__main__":
    import sys

    asyncio.run(prepare_case(Path(sys.argv[1])))
