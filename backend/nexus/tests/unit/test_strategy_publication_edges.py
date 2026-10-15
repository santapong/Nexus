"""Bounded exact native edge reads from actual-shaped SQL responses; no database mutation."""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import BrainReadScope
from nexus.company.strategy.publication_identity import prepare_strategy_publication
from nexus.company.strategy.publication_rows import publication_layout, require_layout_edges_locked
from nexus.tests.unit.strategy_producer_fixture import producer_case


@pytest.mark.parametrize(
    "variant",
    [
        "exact",
        "missing_bundle",
        "foreign_artifact",
        "extra_resource",
        "missing_source",
        "extra_evidence",
    ],
)
async def test_all_four_edge_sets_must_match_without_good_subset_selection(variant: str) -> None:
    snapshot, policy = producer_case()
    prepared = prepare_strategy_publication(
        snapshot,
        policy,
        UUID(int=501),
        ResourceRef(company_id=snapshot.company_id, resource_id=UUID(int=500)),
    )
    scope = BrainReadScope(
        company_id=snapshot.company_id,
        workspace_id=UUID(int=3),
        principal_id=UUID(int=4),
        operation_id=UUID(int=502),
        trace_id=UUID(int=6),
    )
    layout = publication_layout(prepared)[1]
    groups = [
        [row.artifact_revision_id for row in layout.inputs],
        list(snapshot.inputs.required_resource_ids),
        [row.source_revision_id for row in snapshot.inputs.contributors],
        [row.evidence_id for row in snapshot.inputs.evidence],
    ]
    if variant == "missing_bundle":
        groups[0].pop()
    elif variant == "foreign_artifact":
        groups[0][0] = UUID(int=999)
    elif variant == "extra_resource":
        groups[1].append(UUID(int=999))
    elif variant == "missing_source":
        groups[2].clear()
    elif variant == "extra_evidence":
        groups[3].append(UUID(int=999))
    results = []
    for group in groups:
        result = MagicMock()
        result.all.return_value = group
        results.append(result)
    session = MagicMock(spec=AsyncSession)
    session.scalars = AsyncMock(side_effect=results)
    if variant == "exact":
        await require_layout_edges_locked(session, scope, snapshot.inputs, layout)
        assert session.scalars.await_count == 4
    else:
        with pytest.raises(ValueError):
            await require_layout_edges_locked(session, scope, snapshot.inputs, layout)
    for call in session.scalars.await_args_list:
        assert "LIMIT" in str(call.args[0])
