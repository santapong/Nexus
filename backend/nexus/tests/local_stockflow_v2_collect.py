"""Read-only known v2 result/provenance/counter/cleanup observation; never rerun."""

import asyncio
import hashlib

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.settings import settings
from nexus.tests.local_stockflow_collect import _collect
from nexus.tests.local_stockflow_next_packet import NEXT_ROOT
from nexus.tests.stockflow_packet_contracts import PreparedState, ReviewPacket


async def collect() -> None:
    raw = await asyncio.to_thread((NEXT_ROOT / "prelaunch.json").read_bytes)
    if (
        hashlib.sha256(raw).hexdigest()
        != "7221951e0ae7256f1f00231f5e23041e5fc72c2153df08fa2f406110ddde6bde"
    ):
        raise ValueError("Actual reviewed v2 packet changed")
    packet = ReviewPacket.model_validate_json(raw)
    state_raw = await asyncio.to_thread((NEXT_ROOT / "native-state.json").read_bytes)
    if hashlib.sha256(state_raw).hexdigest() != packet.state_sha256:
        raise ValueError("Native state changed")
    state = PreparedState.model_validate_json(state_raw)
    url = make_url(settings.company_test_database_url)
    if url.database != "nexus_company_test_builder":
        raise ValueError("Assigned retained builder DB only")
    engine = create_async_engine(url.set(username="nexus_company_app"))
    try:
        await _collect(
            async_sessionmaker(engine, expire_on_commit=False),
            state,
            packet,
            NEXT_ROOT / "verified-result-observation.json",
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(collect())
