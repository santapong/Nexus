"""Exact known v3 receipt/source/output observation; never prepares or invokes commands."""

from __future__ import annotations

import argparse
import asyncio
import hashlib

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.settings import settings
from nexus.tests.local_stockflow_collect import _collect
from nexus.tests.local_stockflow_v3_prepare import V3_ROOT
from nexus.tests.stockflow_packet_contracts import PreparedState, ReviewPacket


async def collect(expected_packet_sha256: str) -> None:
    packet_raw = await asyncio.to_thread((V3_ROOT / "prelaunch.json").read_bytes)
    if hashlib.sha256(packet_raw).hexdigest() != expected_packet_sha256:
        raise ValueError("Reviewed v3 packet changed")
    packet = ReviewPacket.model_validate_json(packet_raw)
    state_raw = await asyncio.to_thread((V3_ROOT / "native-state.json").read_bytes)
    if hashlib.sha256(state_raw).hexdigest() != packet.state_sha256:
        raise ValueError("Exact native state changed")
    state = PreparedState.model_validate_json(state_raw)
    url = make_url(settings.company_test_database_url)
    if url.database != "nexus_company_test_builder":
        raise ValueError("Only assigned retained builder database supported")
    engine = create_async_engine(url.set(username="nexus_company_app"))
    try:
        await _collect(
            async_sessionmaker(engine, expire_on_commit=False),
            state,
            packet,
            V3_ROOT / "verified-result-observation.json",
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet-sha256", required=True)
    asyncio.run(collect(parser.parse_args().packet_sha256))
