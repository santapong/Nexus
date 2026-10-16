"""Exact declared Nexus builder descriptions never grant an effect."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from nexus.builder.coding_templates import CodingBuilderTemplate
from nexus.tests.unit.test_coding_intent import prepared_case


def test_template_rejects_missing_origin_and_server_check_policy() -> None:
    prepared, _, _, _ = prepared_case()
    with pytest.raises(ValueError):
        CodingBuilderTemplate.model_validate({"company_id": str(prepared.request.company_id)})


async def guard_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Actual read/guard constructors; supplied native metadata is not an intent permit."""
    from types import SimpleNamespace

    from nexus.builder.coding_guard import CodingBuilderSourceGuard
    from nexus.builder.coding_templates import CodingBuilderEntry, CodingBuilderServices
    from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
    from nexus.builder.contained_services import ContainmentServices
    from nexus.builder.source_guard import BuilderSourceGuard, RegisteredBuilderSource
    from nexus.company.management.canonical import canonical_sha256
    from nexus.company.management.planning_native_facts import clock_us
    from nexus.tests.unit.test_coding_publication_origin import origin_case
    from nexus.tests.unit.test_contained_scope import expectation

    value = await origin_case(tmp_path, monkeypatch)
    reader = value.origin_reader
    proof = await reader.load(
        value.builder_lease,
        value.builder_credential,
        value.builder_spec,
        end_us=clock_us() + 20_000_000,
    )
    spec, policy = value.builder_spec, value.builder_policy
    template = CodingBuilderTemplate(
        company_id=spec.job.company_id,
        goal_id=reader.admission.goal.goal_id,
        admission_sha256=canonical_sha256(reader.admission),
        c_action_id=reader.rules.action_id,
        origin=value.published.origin.artifact,
        protected_patch=value.published.patch.artifact,
        source_metadata=value.prepared.sources[0].artifact,
        repository=spec.job.source,
        policy=policy,
        architecture=spec.job.architecture,
        commands=spec.job.commands,
        write_paths=spec.job.write_paths,
        artifact_paths=spec.job.artifact_paths,
        limits=spec.job.limits,
        output_resource=spec.output_resource,
    )
    expected = expectation().model_copy(
        update={
            key: getattr(spec.job, key)
            for key in ("company_id", "task_id", "trace_id", "run_id", "action_id")
        }
    )
    contained = ContainmentServices(expected, ContainmentEvidenceStore(tmp_path / "contained"))
    original = BuilderSourceGuard(
        spec,
        policy,
        value.builder_lease,
        value.builder_credential.identity,
        RegisteredBuilderSource(value.publisher.repository._repository, template.source_metadata),
        reader.artifacts,
        reader.freshness,
        reader.catalog,
        containment=contained,
    )
    guard = CodingBuilderSourceGuard(original, value.builder_credential, reader, template, proof)
    entries = []
    for slot in reader.admission.slots[5:7]:
        target = next(
            row.resource for row in reader.catalog.resources if row.symbol == slot.tool.resource
        )
        entries.append(
            CodingBuilderEntry(
                slot.child.binding, template.model_copy(update={"output_resource": target})
            )
        )
    services = CodingBuilderServices(reader, tuple(entries))
    return SimpleNamespace(
        value=value,
        guard=guard,
        original=original,
        template=template,
        proof=proof,
        services=services,
        contained=contained,
    )


async def test_actual_guard_rejects_reader_and_original_native_graph_splices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = await guard_case(tmp_path, monkeypatch)
    value.guard.require_composition()
    with monkeypatch.context() as patch:
        patch.setattr(value.guard.reader, "factory", object())
        with pytest.raises(ValueError):
            value.guard.require_composition()
    with monkeypatch.context() as patch:
        patch.setattr(value.original, "spec", value.original.spec.model_copy())
        with pytest.raises(ValueError):
            value.guard.require_composition()
    value.guard.require_composition()


async def test_fixed_template_cannot_omit_a_declared_check_or_change_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.builder.coding_templates import checked_template, require_coding_builder_spec

    value = await guard_case(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        checked_template(
            value.template.model_copy(update={"commands": value.template.commands[:1]})
        )
    changed = value.original.spec.model_copy(
        update={
            "protected_patch": value.template.protected_patch.model_copy(
                update={"sha256": "f" * 64}
            )
        }
    )
    with pytest.raises(ValueError):
        require_coding_builder_spec(
            value.template,
            value.services.entries[0].binding,
            changed,
            value.original.policy,
            value.original.source.metadata,
        )
    assert value.value.native.hold.actual_usd == value.proof.origin.actual_usd
