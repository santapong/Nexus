"""Dual immutable row/graph component tests; provenance delivery is explicitly mocked."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.cycle_artifacts.common import CycleKind
from nexus.company.cycle_artifacts.publication_contracts import CycleArtifactRule
from nexus.tests.unit.cycle_deliverable_fixture import deliverable_case
from nexus.tests.unit.cycle_publication_row_fixture import row_case


def row_rule(kind: CycleKind = "presentation") -> CycleArtifactRule:
    return row_case(kind).write_rule


@pytest.mark.parametrize("kind", ["presentation", "support"])
def test_both_ordered_parts_share_original_manifest_without_future_self_inputs(
    kind: CycleKind,
) -> None:
    from nexus.company.cycle_artifacts.publication_rows import author_layout

    case, rule = deliverable_case(kind), row_rule(kind)
    rule = rule.model_copy(
        update={"company_id": case.basis.company_id, "target": case.basis.target}
    )
    rows = author_layout(case.prepared, rule)
    assert tuple(row.reference for row in rows) == tuple(
        p.artifact for p in case.prepared.manifest.parts
    )
    assert tuple(row.raw for row in rows) == (case.prepared.typed_json, case.prepared.human_export)
    assert all(row.inputs == case.basis.inputs for row in rows)


@pytest.mark.parametrize("present", [(True, False), (False, True), (True, True)])
async def test_partial_or_existing_output_never_repairs_the_pair(
    present: tuple[bool, bool],
) -> None:
    from nexus.company.cycle_artifacts.publication_rows import append_author_locked

    case, rule = deliverable_case(), row_rule()
    rule = rule.model_copy(
        update={"company_id": case.basis.company_id, "target": case.basis.target}
    )
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    session.get = AsyncMock(side_effect=[UUID(int=9) if value else None for value in present])
    scope = BrainReadScope(
        company_id=case.basis.company_id,
        workspace_id=case.basis.author.workspace_id,
        principal_id=case.basis.author.actor_id,
        operation_id=UUID(int=2),
        trace_id=case.basis.author.trace_id,
    )
    with pytest.raises(ValueError):
        await append_author_locked(
            session, scope, case.prepared, rule, "fixture", datetime.now(UTC)
        )
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.parametrize(
    "field,value",
    [
        ("raw_text", "altered"),
        ("media_type", "text/plain"),
        ("resource_id", UUID(int=999)),
        ("storage_symbol", "other"),
        ("derivation_id", UUID(int=999)),
    ],
)
def test_replay_compares_all_immutable_part_fields(field: str, value: object) -> None:
    from nexus.company.cycle_artifacts.publication_rows import author_layout, require_row

    case, rule = deliverable_case(), row_rule()
    rule = rule.model_copy(
        update={"company_id": case.basis.company_id, "target": case.basis.target}
    )
    layout = author_layout(case.prepared, rule)[1]
    ref = layout.reference
    row = BrainArtifactRevision(
        company_id=ref.company_id,
        artifact_id=ref.artifact_id,
        artifact_revision_id=ref.artifact_revision_id,
        revision=ref.revision,
        raw_text=layout.raw.decode(),
        sha256=ref.sha256,
        byte_length=ref.byte_length,
        resource_id=rule.target.resource_id,
        derivation_id=layout.derivation_id,
        media_type=layout.policy.media_type,
        storage_symbol="fixture",
        data_classification=layout.policy.data_classification,
    )
    require_row(row, layout, "fixture")
    setattr(row, field, value)
    with pytest.raises(ValueError):
        require_row(row, layout, "fixture")


def graph_delivery(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, list[object]]:
    """Supply ORM delivery only; actual append/replay/derivation code remains under test."""
    from uuid import uuid5

    from nexus.company.brain.derivation_models import BrainDerivation
    from nexus.company.brain.event_models import BrainEvent
    from nexus.company.cycle_artifacts import publication_rows as module

    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    rows: list[object] = []
    session.add.side_effect, session.add_all.side_effect = rows.append, rows.extend
    session.flush = AsyncMock()

    async def get(model: type[object], key: object) -> object | None:
        fields: dict[type[object], str] = {
            BrainArtifactRevision: "artifact_revision_id",
            BrainDerivation: "derivation_id",
            BrainEvent: "event_id",
        }
        if isinstance(key, dict):
            wanted = key
        else:
            assert isinstance(key, tuple)
            wanted = {"company_id": key[0], fields[model]: key[1]}
        return next(
            (
                r
                for r in rows
                if isinstance(r, model)
                and all(getattr(r, name) == value for name, value in wanted.items())
            ),
            None,
        )

    async def scalars(statement: object) -> MagicMock:
        # SQL shape is inspected; no SQL connection or actual acceptance authority is supplied.
        description = statement.column_descriptions[0]  # type: ignore[attr-defined]
        params = statement.compile().params  # type: ignore[attr-defined]
        parent_name = (
            "artifact_revision_id" if "artifact_revision_id_1" in params else "derivation_id"
        )
        parent = params[parent_name + "_1"]
        selected = [
            getattr(r, description["name"])
            for r in rows
            if isinstance(r, description["entity"]) and getattr(r, parent_name) == parent
        ]
        result = MagicMock()
        result.all.return_value = selected
        return result

    async def event(session: object, scope: BrainReadScope, **values: object) -> None:
        key = str(values["deduplication_key"])
        rows.append(
            BrainEvent(
                company_id=scope.company_id,
                event_id=uuid5(scope.company_id, key),
                kind=values["kind"],
                resource_id=values["resource_id"],
                action_id=values["action_id"],
                deduplication_key=key,
                recorded_at=values["now"],
                trace_id=scope.trace_id,
                operation_id=scope.operation_id,
                source_revision_id=None,
                resource_generation=None,
            )
        )

    session.get, session.scalars = AsyncMock(side_effect=get), AsyncMock(side_effect=scalars)
    monkeypatch.setattr(module, "validate_derivation", AsyncMock())
    monkeypatch.setattr(module, "append_event", event)
    return session, rows


@pytest.mark.parametrize(
    "damage", [None, "input", "resource", "source", "evidence", "event", "time"]
)
async def test_real_two_graph_append_and_replay_detects_each_edge_or_event_splice(
    monkeypatch: pytest.MonkeyPatch,
    damage: str | None,
) -> None:
    # Keep this >50-line append/replay/tamper case so all four graph relations share one baseline.
    from nexus.company.brain.artifact_input_models import (
        BrainArtifactInput,
        BrainArtifactResourceInput,
    )
    from nexus.company.brain.derivation_models import (
        BrainDerivation,
        BrainDerivationEvidence,
        BrainDerivationSource,
    )
    from nexus.company.brain.event_models import BrainEvent
    from nexus.company.cycle_artifacts import publication_rows as module

    item = row_case()
    scope = BrainReadScope(
        company_id=item.case.basis.company_id,
        workspace_id=item.case.basis.author.workspace_id,
        principal_id=item.case.basis.author.actor_id,
        operation_id=uuid5(item.prepared.action_id, "cycle-publication:v1"),
        trace_id=item.case.basis.author.trace_id,
    )
    session, rows = graph_delivery(monkeypatch)
    await module.append_author_locked(
        session, scope, item.prepared, item.write_rule, "fixture", datetime.now(UTC)
    )
    assert sum(isinstance(r, BrainArtifactRevision) for r in rows) == 2
    before = len(rows)
    await module.require_author_replay_locked(
        session, scope, item.prepared, item.write_rule, "fixture"
    )
    assert len(rows) == before

    if damage is None:
        return
    model, field = {
        "input": (BrainArtifactInput, "input_artifact_revision_id"),
        "resource": (BrainArtifactResourceInput, "resource_id"),
        "source": (BrainDerivationSource, "source_revision_id"),
        "evidence": (BrainDerivationEvidence, "evidence_id"),
        "event": (BrainEvent, "trace_id"),
        "time": (BrainDerivation, "recorded_at"),
    }[damage]
    row = next(r for r in rows if isinstance(r, model))
    setattr(row, field, datetime(2020, 1, 1, tzinfo=UTC) if damage == "time" else UUID(int=999))
    with pytest.raises(ValueError):
        await module.require_author_replay_locked(
            session, scope, item.prepared, item.write_rule, "fixture"
        )
    assert len(rows) == before


async def test_independent_verifier_replay_keeps_the_original_author_event_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid5

    from nexus.company.cycle_artifacts import publication_rows as module

    item = row_case()
    author = item.case.basis.author
    scope = BrainReadScope(
        company_id=item.case.basis.company_id,
        workspace_id=author.workspace_id,
        principal_id=author.actor_id,
        operation_id=uuid5(item.prepared.action_id, "cycle-publication:v1"),
        trace_id=author.trace_id,
    )
    session, _ = graph_delivery(monkeypatch)
    await module.append_author_locked(
        session, scope, item.prepared, item.write_rule, "fixture", datetime.now(UTC)
    )
    verifier = item.case.basis.verifier
    own_scope = scope.model_copy(
        update={"principal_id": verifier.actor_id, "trace_id": verifier.trace_id}
    )
    await module.require_author_replay_locked(
        session, own_scope, item.prepared, item.write_rule, "fixture"
    )
