"""Concrete reader path with actual-shaped rows and receipts; all SQL/current authorities mocked."""

from unittest.mock import AsyncMock

import pytest

from nexus.company.brain.artifact_input_models import BrainArtifactInput
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.strategy.input_reader import StrategyInputReader, StrategyProtectedPublication
from nexus.harness.journal_models import JournalAction
from nexus.tests.unit.strategy_publication_reader_fixture import ReaderCase, reader_case


async def read(case: ReaderCase) -> StrategyProtectedPublication:
    return await case.reader.load_original_locked(
        case.source.session,
        case.source.control,
        case.source.scope,
        case.source.credential.identity,
        case.prepared.action_id,
        credential=case.source.credential,
    )


async def test_original_reader_resolves_actual_succeeded_receipt_full_graph_and_original_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = reader_case(monkeypatch)
    original = case.source.original.model_dump_json()
    protected = await read(case)
    assert protected.publication.prepared == case.prepared
    assert protected.publication.original_intent_fence == 1
    assert case.source.original.model_dump_json() == original
    protected.protection.require_time(case.source.clock["now"])
    case.source.session.add.assert_not_called()
    case.source.session.flush.assert_not_awaited()


@pytest.mark.parametrize(
    "fault", ["unknown", "proposal", "missing_bundle", "source_bytes", "bundle_edge", "row_hash"]
)
async def test_declared_compiled_hashes_do_not_replace_native_receipt_source_and_graph(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    case = reader_case(monkeypatch)
    company = case.source.original.company_id
    if fault == "unknown":
        case.effect.state = "outcome_unknown"
    elif fault == "proposal":
        journal = case.rows[(JournalAction, case.prepared.action_id)]
        assert isinstance(journal, JournalAction)
        journal.proposal_hash = "a" * 64
    elif fault == "missing_bundle":
        case.rows.pop(
            (
                BrainArtifactRevision,
                (company, case.prepared.compiled.original_bundle.artifact.artifact_revision_id),
            )
        )
    elif fault == "source_bytes":
        from nexus.company.strategy import source_inputs

        # The test inspects its module-local patched dependency.
        mocked_bundles = source_inputs.bundles  # type: ignore[attr-defined]
        assert isinstance(mocked_bundles, AsyncMock)
        bundle = mocked_bundles.return_value[case.source.original.sources[0].evidence.evidence_id]
        bundle.artifact.raw_text = "changed actual source bytes"
    elif fault == "bundle_edge":
        case.edges[
            (BrainArtifactInput.__tablename__, case.prepared.brief.artifact_revision_id)
        ].pop()
    else:
        artifact = case.rows[
            (BrainArtifactRevision, (company, case.prepared.brief.artifact_revision_id))
        ]
        assert isinstance(artifact, BrainArtifactRevision)
        artifact.sha256 = "0" * 64
    with pytest.raises(ValueError):
        await read(case)


async def test_direct_expiry_dto_cannot_replace_genuine_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = reader_case(monkeypatch)
    with pytest.raises(ValueError):
        await case.reader.load_original_locked(
            case.source.session,
            case.source.control,
            case.source.scope,
            case.source.credential.identity,
            case.prepared.action_id,
            credential=object(),  # type: ignore[arg-type]
        )
    case.row_get.assert_not_awaited()


@pytest.mark.parametrize("fault", ["tool", "resource", "storage"])
def test_reader_constructor_requires_exact_server_tool_resource_and_storage(
    fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = reader_case(monkeypatch)
    catalog = case.reader.catalog
    blobs = case.reader.blobs
    if fault == "tool":
        catalog = catalog.model_copy(update={"tools": ()})
    elif fault == "resource":
        catalog = catalog.model_copy(update={"resources": ()})
    else:
        blobs = object()  # type: ignore[assignment]
    with pytest.raises(ValueError):
        StrategyInputReader(
            case.reader.artifacts,
            case.reader.policies,
            catalog,
            case.reader.production_policy,
            blobs=blobs,
            write_rule=case.reader.rules.write,
            check_rule=case.reader.rules.check,
        )
