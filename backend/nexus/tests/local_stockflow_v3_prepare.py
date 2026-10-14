"""One genuine third pair/second revision preparation; no project engine invocation."""

from __future__ import annotations

import asyncio

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.settings import settings
from nexus.tests.local_builder_model_observation import EVIDENCE, build
from nexus.tests.local_builder_model_requalification import qualify
from nexus.tests.local_stockflow_next_packet import prepare
from nexus.tests.local_stockflow_packet import ROOT, write_private
from nexus.tests.local_stockflow_reobserve import reobserve
from nexus.tests.local_stockflow_siblings import partition
from nexus.tests.stockflow_packet_contracts import PreparedState

V3_ROOT = ROOT / "node-v3-sibling"


async def model_check() -> None:
    V3_ROOT.mkdir(mode=0o700)
    await qualify(V3_ROOT, "builder-offline-model-refresh-20261014-v2")
    await build(V3_ROOT, EVIDENCE / "model-requalification-v3-existing-fixtures.log")


async def prepare_native() -> None:
    state = PreparedState.model_validate_json(
        await asyncio.to_thread((ROOT / "accepted-preparation-state.json").read_bytes)
    )
    catalog = PlanAdmissionCatalog.model_validate_json(
        await asyncio.to_thread((V3_ROOT / "refreshed-catalog.json").read_bytes)
    )
    url = make_url(settings.company_test_database_url)
    if url.database != "nexus_company_test_builder":
        raise ValueError("Only retained builder fixture database is supported")
    engine = create_async_engine(url.set(username="nexus_company_app"))
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        metadata = await reobserve(
            factory,
            state,
            revision="observed-20261014-3",
            receipt_path=V3_ROOT / "source-reobservation-accepted-receipt.json",
        )
        current = PreparedState.model_validate_json(
            state.model_copy(update={"catalog": catalog, "metadata": metadata}).model_dump_json()
        )
        await asyncio.to_thread(
            write_private,
            V3_ROOT / "accepted-preparation-state.json",
            current.model_dump_json(indent=2).encode(),
        )
        await partition(factory, current, V3_ROOT / "sibling-revision-receipt.json")
    finally:
        await engine.dispose()
    await prepare(
        preparation_state=V3_ROOT / "accepted-preparation-state.json",
        partition_receipt=V3_ROOT / "sibling-revision-receipt.json",
        destination=V3_ROOT,
        policy_symbol="stockflow.nominated.node.v3",
        model_receipt=V3_ROOT / "model-requalification-receipt.json",
        source_receipt=V3_ROOT / "source-reobservation-accepted-receipt.json",
    )


async def main() -> None:
    await model_check()
    await prepare_native()


if __name__ == "__main__":
    asyncio.run(main())
