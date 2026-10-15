"""Scoped SQL-shaped read adapters; actual queries/role/privacy are not PostgreSQL proof."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.directory_models import DirectoryMembership
from nexus.company.management.acceptance_models import ManagementAcceptanceProof
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.strategy import (
    current_proof_material,
    current_proof_read,
    current_proof_reader,
    original_reader,
    owner_reader,
    verifier_facts,
)
from nexus.company.strategy.artifact_contracts import PreparedStrategyArtifact, StrategyArtifactRule
from nexus.company.strategy.check_rows import require_strategy_check_replay_locked
from nexus.company.strategy.publication_contracts import PreparedStrategyPublication
from nexus.company.strategy.publication_rows import require_strategy_publication_replay_locked
from nexus.execution.runtime_models import EffectIntent

if TYPE_CHECKING:
    from nexus.tests.unit.strategy_current_proof_fixture import ProofCase


def install_proof_reads(
    case: ProofCase,
    proofs: list[ManagementAcceptanceProof],
    event: BrainEvent,
    manifest: GeneratedArtifactInputs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delegate real immutable graph comparisons while replacing only native query delivery."""
    # Keep this >50-line adapter's exact row/projection and nominated final-clock seam cohesive.
    base, source = case.base, case.base.source
    company = case.scope.company_id
    original_get, original_scalars = (
        source.session.get.side_effect,
        source.session.scalars.side_effect,
    )

    async def get(model: type[object], lookup: object) -> object:
        if model is BrainArtifactRevision:
            assert isinstance(lookup, tuple)
            case.body_gets.append(lookup[1])
        if model is DirectoryMembership:
            case.owner_reads[0] += 1
            if case.owner_reads[0] == 4 and case.final_deadline[0] is not None:
                source.clock["now"] = case.final_deadline[0]
        return await original_get(model, lookup)

    async def metadata(statement: object) -> MagicMock:
        params = statement.compile().params  # type: ignore[attr-defined]
        row = cast(
            BrainArtifactRevision | None,
            base.rows.get((BrainArtifactRevision, (company, params["artifact_revision_id_1"]))),
        )
        result = MagicMock()
        values: tuple[object, ...] | None = (
            None
            if row is None
            else (
                row.artifact_id,
                row.artifact_revision_id,
                row.revision,
                row.sha256,
                row.byte_length,
            )
        )
        if values is not None and len(statement.column_descriptions) == 6:  # type: ignore[attr-defined]
            assert row is not None
            values += (row.resource_id,)
        result.one_or_none.return_value = values
        return result

    async def scalars(statement: object) -> MagicMock:
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity in {EffectIntent, ManagementAcceptanceProof}:
            result = MagicMock()
            result.all.side_effect = lambda: case.actions if entity is EffectIntent else proofs
            return result
        return cast(MagicMock, await original_scalars(statement))

    async def scalar(statement: object) -> object:
        query = str(statement)
        if "pg_roles" in query:
            return case.privileged[0]
        if "company_brain_events" in query:
            return event
        return UUID(int=999) if case.invalid[0] else None

    async def clock(*_: object) -> datetime:
        return source.clock["now"]

    async def bs_graph(
        session: AsyncSession,
        scope: BrainReadScope,
        prepared: PreparedStrategyPublication,
        storage: str,
    ) -> None:
        case.graph_calls["B/S"] += 1
        await require_strategy_publication_replay_locked(session, scope, prepared, storage)

    async def c_graph(
        session: AsyncSession,
        scope: BrainReadScope,
        action: UUID,
        prepared: PreparedStrategyArtifact,
        rule: StrategyArtifactRule,
        storage: str,
    ) -> None:
        case.graph_calls["C"] += 1
        await require_strategy_check_replay_locked(session, scope, action, prepared, rule, storage)

    source.session.get, source.session.execute = (
        AsyncMock(side_effect=get),
        AsyncMock(side_effect=metadata),
    )
    source.session.scalars, source.session.scalar = (
        AsyncMock(side_effect=scalars),
        AsyncMock(side_effect=scalar),
    )
    monkeypatch.setattr(
        current_proof_material, "native_manifest", AsyncMock(return_value=(manifest, "internal"))
    )
    for module in (
        current_proof_material,
        current_proof_reader,
        current_proof_read,
        verifier_facts,
        owner_reader,
    ):
        monkeypatch.setattr(module, "db_now", clock)
    monkeypatch.setattr(original_reader, "require_strategy_publication_replay_locked", bs_graph)
    monkeypatch.setattr(current_proof_material, "require_strategy_check_replay_locked", c_graph)
