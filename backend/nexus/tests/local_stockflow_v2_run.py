"""Execute only a reviewed sibling v2 packet through the same actual native M1 runner."""

from __future__ import annotations

import argparse
import asyncio
import hashlib

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.settings import settings
from nexus.tests.local_stockflow_next_packet import NEXT_ROOT
from nexus.tests.local_stockflow_run import _run
from nexus.tests.stockflow_packet_contracts import PreparedState, ReviewPacket


async def execute(expected_sha: str) -> None:
    raw = await asyncio.to_thread((NEXT_ROOT / "prelaunch.json").read_bytes)
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("Exact reviewed v2 packet changed")
    packet = ReviewPacket.model_validate_json(raw)
    state_raw = await asyncio.to_thread((NEXT_ROOT / "native-state.json").read_bytes)
    if hashlib.sha256(state_raw).hexdigest() != packet.state_sha256:
        raise ValueError("Native v2 state differs from reviewed packet")
    state = PreparedState.model_validate_json(state_raw)
    url = make_url(settings.company_test_database_url)
    if url.database != "nexus_company_test_builder":
        raise ValueError("Assigned retained builder database only")
    engine = create_async_engine(url.set(username="nexus_company_app"))
    try:
        await _run(async_sessionmaker(engine, expire_on_commit=False), state, packet, NEXT_ROOT)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet-sha256", required=True)
    asyncio.run(execute(parser.parse_args().packet_sha256))
