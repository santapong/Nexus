"""Manual disposable prepare only: real nominated source/native approval, no project execution."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.builder.node_recipe import config_text, node_script, wrappers
from nexus.builder.node_runtime_plan import node_argv
from nexus.builder.runtime_plan import PreparedSources
from nexus.builder.snapshot import committed_archive, extract_source
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CostHold
from nexus.settings import settings
from nexus.tests.builder_node_support import node_scenario
from nexus.tests.builder_stockflow_support import qualification_limits, qualified_inputs
from nexus.tests.integration.test_company_directory import ACTOR, migrate
from nexus.tests.integration.test_company_execution_store import identity

ROOT = Path("/tmp/nexus-builder-stockflow-native-20261014-v1")


def inspection_files(base: Path, raw: bytes, spec_json: str, policy_json: str) -> None:
    from nexus.builder.execution_contracts import BuilderExecutionSpec
    from nexus.builder.policy import BuilderToolPolicy

    spec = BuilderExecutionSpec.model_validate_json(spec_json)
    policy = BuilderToolPolicy.model_validate_json(policy_json)
    base.mkdir(mode=0o700)
    extract_source(raw, spec.job.source, base / "baseline")
    extract_source(raw, spec.job.source, base / "post")
    commands = base / "node-commands"
    commands.mkdir(mode=0o700)
    for key, text in wrappers().items():
        (commands / f"{key}.sh").write_text(text)
    (commands / "offline.npmrc").write_text(config_text())
    (base / "entrypoint.sh").write_text(node_script(spec, policy))
    (base / "resolv.conf").write_bytes(b"")
    for path in (*commands.iterdir(), base / "entrypoint.sh", base / "resolv.conf"):
        path.chmod(0o600)


async def prepare() -> None:
    url = make_url(settings.company_test_database_url)
    if url.database != "nexus_company_test_builder":
        raise ValueError("Only the assigned disposable builder database is supported")
    qualified = await qualified_inputs()
    ROOT.mkdir(mode=0o700, exist_ok=False)
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        factory = async_sessionmaker(app, expire_on_commit=False)
        item = await node_scenario(
            factory, ROOT, qualified=qualified, limits=qualification_limits()
        )
        await item.runner.execution.release(item.lease, identity(ACTOR))
        raw = await committed_archive(qualified[0], item.spec.job.source)
        base = ROOT / "argv-inspection"
        await asyncio.to_thread(
            inspection_files,
            base,
            raw,
            item.spec.model_dump_json(),
            item.guard.policy.model_dump_json(),
        )
        described = node_argv(
            item.spec,
            item.guard.policy,
            item.runner.capabilities,
            PreparedSources(base / "baseline", base / "post"),
            base,
            qualified[2],
        )
        actual_base = (
            item.runner.jobs_root / f"{item.spec.job.company_id.hex}-{item.spec.job.action_id.hex}"
        )
        actual_argv = tuple(value.replace(str(base), str(actual_base)) for value in described)
        state = {
            "scope": "synthetic identities; actual nominated historical source; prepared only",
            "spec": item.spec.model_dump(mode="json"),
            "action": item.action.model_dump(mode="json"),
            "policy": item.guard.policy.model_dump(mode="json"),
            "catalog": item.guard.catalog.model_dump(mode="json"),
            "capabilities": item.runner.capabilities.model_dump(mode="json"),
            "metadata": item.guard.source.metadata.model_dump(mode="json"),
            "released_lease": item.lease.model_dump(mode="json"),
            "source_policy": item.guard.freshness._policies.policy(
                "acceptance.fixture.9900"
            ).model_dump(mode="json"),
            "source_repository": str(qualified[0]),
        }
        raw_state = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
        await asyncio.to_thread(write_private, ROOT / "native-state.json", raw_state)
        async with runtime_transaction(
            factory, lease_scope(item.lease), identity(ACTOR), allow_paused=True
        ) as (session, _, _):
            intents = await session.scalar(select(func.count()).select_from(EffectIntent))
            holds = tuple(
                (
                    await session.scalars(
                        select(CostHold).where(
                            CostHold.company_id == item.spec.job.company_id,
                            CostHold.task_id == item.spec.job.task_id,
                        )
                    )
                ).all()
            )
        packet = {
            "scope": state["scope"],
            "source_event": "nominated bb7cc008 historical commit; not current business-readiness",
            "state_sha256": hashlib.sha256(raw_state).hexdigest(),
            "action": state["action"],
            "action_sha256": action_hash(item.action),
            "policy": state["policy"],
            "spec": state["spec"],
            "actual_argv": actual_argv,
            "actual_native_intents": intents,
            "actual_native_holds": [
                {
                    "action_id": str(row.action_id),
                    "state": row.state,
                    "reserved_usd": str(row.amount_usd),
                    "actual_usd": str(row.actual_usd) if row.actual_usd is not None else None,
                }
                for row in holds
            ],
            "lease_released": True,
            "input_qualification": "bounded archive/SRI/manifest/tree bytes and modes passed",
            "source_archive_bytes": len(raw),
            "project_processes_started": 0,
            "limits": item.spec.job.limits.model_dump(mode="json"),
            "patch": "none; unchanged baseline and post toolchain qualification",
            "holds_and_cost": "authorization reserved holds; local actual USD unknown",
            "activation": "disabled; no worker/provider/Pi/network/image-pull/deployment/email",
        }
        await asyncio.to_thread(
            write_private, ROOT / "prelaunch.json", json.dumps(packet, indent=2).encode()
        )
    finally:
        await app.dispose()
        await admin.dispose()


def write_private(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)
    path.chmod(0o600)


if __name__ == "__main__":
    asyncio.run(prepare())
