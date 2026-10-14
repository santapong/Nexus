"""Exact reviewed v3 native action execution, with no automatic reissue or activation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.settings import settings
from nexus.tests.local_stockflow_run import _run
from nexus.tests.local_stockflow_v3_prepare import V3_ROOT
from nexus.tests.stockflow_packet_contracts import PreparedState, ReviewPacket


async def execute(expected_packet_sha256: str) -> None:
    packet_raw = await asyncio.to_thread((V3_ROOT / "prelaunch.json").read_bytes)
    if hashlib.sha256(packet_raw).hexdigest() != expected_packet_sha256:
        raise ValueError("Reviewed v3 prelaunch packet changed")
    packet = ReviewPacket.model_validate_json(packet_raw)
    state_raw = await asyncio.to_thread((V3_ROOT / "native-state.json").read_bytes)
    if hashlib.sha256(state_raw).hexdigest() != packet.state_sha256:
        raise ValueError("Prepared v3 native state differs from reviewed packet")
    state = PreparedState.model_validate_json(state_raw)
    url = make_url(settings.company_test_database_url)
    if url.database != "nexus_company_test_builder":
        raise ValueError("Only assigned retained builder database supported")
    engine = create_async_engine(url.set(username="nexus_company_app"))
    try:
        await _run(async_sessionmaker(engine, expire_on_commit=False), state, packet, V3_ROOT)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet-sha256", required=True)
    asyncio.run(execute(parser.parse_args().packet_sha256))
