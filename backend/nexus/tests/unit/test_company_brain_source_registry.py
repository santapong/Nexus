"""Configured symbols and immutable source bindings cannot be supplied by document content."""

from uuid import UUID

import pytest

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import SourceTime
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.brain.source_registry import SourcePolicy, SourceRegistry, SourceSnapshot
from nexus.company.brain.sources import SourceRegistration


def policy(**changes: object) -> SourcePolicy:
    return SourcePolicy.model_validate(
        {
            "source_symbol": "fixture.source.v1",
            "authority_profile": "fixture.reported.v1",
            "data_classification": "internal",
            "media_type": "text/plain",
            "parser_version": "utf8-identity-v1",
            "chunker_version": "utf8-sections-v1",
            "search_config": "simple",
            "freshness_seconds": None,
            "allowed_external_keys": frozenset({"document-1"}),
        }
        | changes
    )


def registration() -> SourceRegistration:
    return SourceRegistration(
        company_id=UUID(int=1),
        source_id=UUID(int=2),
        resource=ResourceRef(company_id=UUID(int=1), resource_id=UUID(int=3)),
        source_symbol="fixture.source.v1",
        external_key="document-1",
    )


class Reader:
    def __init__(self, **changes: object) -> None:
        self.changes = changes
        self.calls = 0

    async def read(self, source: SourceRegistration, revision: str) -> SourceSnapshot:
        self.calls += 1
        return SourceSnapshot.model_validate(
            {
                "company_id": source.company_id,
                "source_id": source.source_id,
                "source_symbol": source.source_symbol,
                "external_key": source.external_key,
                "revision": revision,
                "raw_bytes": b"typed exact source bytes",
                "source_event": SourceTime(precision="unknown", value=None, basis="fixture"),
            }
            | self.changes
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"company_id": UUID(int=9)},
        {"source_id": UUID(int=9)},
        {"source_symbol": "foreign.source.v1"},
        {"external_key": "document-2"},
        {"revision": "r2"},
    ],
)
async def test_adapter_cannot_rebind_registered_source(changes: dict[str, object]) -> None:
    with pytest.raises(BrainDeniedError):
        await SourceRegistry((policy(),), Reader(**changes)).read(registration(), "r1")


async def test_unknown_or_unlisted_symbol_never_invokes_reader() -> None:
    reader = Reader()
    registry = SourceRegistry((policy(allowed_external_keys=frozenset()),), reader)
    with pytest.raises(BrainDeniedError):
        await registry.read(registration(), "r1")
    with pytest.raises(BrainDeniedError):
        registry.policy("unknown.v1")
    assert reader.calls == 0


async def test_derived_source_requires_manifest_and_declared_byte_bound() -> None:
    with pytest.raises(BrainDeniedError):
        await SourceRegistry((policy(origin_kind="derived"),), Reader()).read(registration(), "r1")
    with pytest.raises(BrainDeniedError):
        await SourceRegistry((policy(max_bytes=1),), Reader()).read(registration(), "r1")
