"""Frozen evaluator/fixture boundaries and actual offline SDK message capture."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.context import ContextLimits
from nexus.company.brain.context_render import render_context
from nexus.company.brain.sources import SourceRegistration
from nexus.tests.brain_evaluator import CRITICAL, evaluate, frozen_goldens
from nexus.tests.brain_projection_fixtures import Projection
from nexus.tests.brain_sdk_capture import SDKCapture, capture_context
from nexus.tests.brain_source_fixtures import (
    FIXTURES,
    FixtureSourceReader,
    SealedManagementProvider,
    frozen_sources,
)
from nexus.tests.unit.test_company_brain_context_render import SCOPE, authority, head, material


def test_original_30_cases_and_16_critical_are_hash_frozen() -> None:
    pack = frozen_goldens()
    assert len(pack.cases) == 30
    assert {row.case_id for row in pack.cases if row.critical} == CRITICAL


def test_missing_cases_fail_without_reducing_denominator() -> None:
    receipt = evaluate(())
    assert len(receipt.cases) == 30 and receipt.passed_count == 0
    assert receipt.critical_passed_count == 0 and receipt.threshold_passed is False
    assert all(row.observation_sha256 is None and not row.passed for row in receipt.cases)


def test_runtime_fixture_provider_refuses_golden_paths_and_has_no_golden_imports() -> None:
    with pytest.raises(ValueError, match="runtime source"):
        frozen_sources(FIXTURES / "golden.json")
    from nexus.tests import brain_source_fixtures

    source = Path(brain_source_fixtures.__file__).read_text()
    imports = tuple(
        node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)
    )
    assert not any(node.module and "evaluator" in node.module for node in imports)


def test_typed_sealed_projections_cannot_claim_live_completion_or_create_writer() -> None:
    pack = frozen_sources()
    setup = next(row for row in pack.case_setup if row.case_id == "B25")
    provider = SealedManagementProvider(pack)
    row = provider.for_case("B25", setup.company_id)[0]
    assert row.authority == "sealed_test_setup_only_not_live_execution_or_model_output"
    assert not hasattr(provider, "register") and not hasattr(provider, "publish")
    changed = row.model_dump_json().replace('"work_completed":false', '"work_completed":true')
    with pytest.raises(ValidationError):
        TypeAdapter(Projection).validate_json(changed)


async def test_source_provider_returns_exact_declared_source_bytes_and_precision() -> None:
    pack = frozen_sources()
    source = pack.source_revisions[0]
    result = await FixtureSourceReader(pack).read(
        SourceRegistration(
            company_id=source.company_id,
            source_id=source.source_id,
            resource=ResourceRef(company_id=source.company_id, resource_id=source.acl_resource_id),
            source_symbol=source.source_symbol,
            external_key=source.external_key,
        ),
        source.revision,
    )
    assert result.raw_bytes == source.text.encode() and result.source_event.precision == "day"


async def test_actual_offline_sdk_request_preserves_attachment_workspace_and_trusted_criteria() -> (
    None
):
    attachment, workspace = material(), material("WORKSPACE_SENTINEL prerequisite", identifier=40)
    context = render_context(
        SCOPE,
        authority(),
        ContextLimits(policy_version="context-v1"),
        (attachment, workspace),
        (head(attachment), head(workspace)),
        question="Find prerequisites",
        purposes={
            attachment.record.evidence_id: "attachment",
            workspace.record.evidence_id: "workspace",
        },
    )
    result = await capture_context(context)
    assert "ATTACHMENT_SENTINEL" in result.request_json
    assert "WORKSPACE_SENTINEL" in result.request_json
    assert all(term in result.request_json for term in authority().acceptance)
    assert SDKCapture.model_validate_json(result.model_dump_json()) == result
    changed = result.model_dump_json().replace("Find prerequisites", "Changed question")
    with pytest.raises(ValidationError):
        SDKCapture.model_validate_json(changed)
