"""Every selected-builder field is supplied-data consistency, never execution authority."""

from dataclasses import replace
from uuid import UUID

import pytest

from nexus.builder.contracts import BuilderLimits
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.runtime_identity import RUNTIME_V2_METHOD_SHA256
from nexus.company.management.canonical import canonical_sha256
from nexus.tests.unit.selected_strategy_pins_fixture import SelectedCase, selected_case


@pytest.mark.parametrize("verifier", [False, True])
def test_exact_native_role_description_returns_no_authority(verifier: bool) -> None:
    case = selected_case(verifier)
    before = tuple(row.model_dump_json() for row in (case.spec, case.policy, case.template))
    case.check()
    assert tuple(row.model_dump_json() for row in (case.spec, case.policy, case.template)) == before


def changed(case: SelectedCase, group: str, field: str, value: object) -> SelectedCase:
    if group == "job":
        return replace(
            case,
            spec=case.spec.model_copy(
                update={"job": case.spec.job.model_copy(update={field: value})}
            ),
        )
    original = getattr(case, group)
    return replace(case, **{group: original.model_copy(update={field: value})})


@pytest.mark.parametrize(
    "group,field,value",
    [
        *(
            ("job", field, UUID(int=999))
            for field in ("company_id", "task_id", "trace_id", "run_id", "workspace_id", "actor_id")
        ),
        ("job", "policy_symbol", "other.policy"),
        ("job", "resource_symbol", "other.resource"),
        ("job", "architecture", "arm64"),
        ("job", "patch_sha256", "f" * 64),
        ("job", "write_paths", ("packages/shared/src/csv",)),
        ("job", "artifact_paths", ("other",)),
        ("job", "network", "host"),
        ("spec", "runtime_recipe", "nexus.builder.runtime.v1"),
        ("spec", "policy_sha256", "f" * 64),
        ("spec", "protected_patch", None),
        ("spec", "output_resource", None),
        ("spec", "runtime_inputs", None),
        ("candidate_policy", "goal_id", UUID(int=999)),
        ("candidate_policy", "source_manifest_sha256", "f" * 64),
        ("candidate", "patch_sha256", "f" * 64),
        ("candidate", "method_sha256", "f" * 64),
        ("candidate", "candidate_id", "other-choice"),
        ("candidate", "write_paths", ("other",)),
        ("template", "candidate_policy_sha256", "f" * 64),
        ("template", "candidate_scope_sha256", "f" * 64),
        ("binding", "workflow_name", "company.cycle.artifact"),
        ("binding", "workflow_version", "v2"),
        ("binding", "model_profile", "reasoning"),
    ],
)
def test_each_independent_spec_policy_choice_or_role_splice_denies(
    group: str, field: str, value: object
) -> None:
    with pytest.raises(ValueError):
        changed(selected_case(), group, field, value).check()


@pytest.mark.parametrize("field", ["repository_symbol", "commit", "tree", "archive_sha256"])
def test_each_repository_pin_is_exact(field: str) -> None:
    case = selected_case()
    value = (
        "other.repo"
        if field == "repository_symbol"
        else "f" * (40 if field in {"commit", "tree"} else 64)
    )
    source = case.spec.job.source.model_copy(update={field: value})
    with pytest.raises(ValueError):
        changed(case, "job", "source", source).check()


@pytest.mark.parametrize("which", ["source_metadata", "protected_patch", "output_resource"])
@pytest.mark.parametrize("field", ["company_id", "identity"])
def test_protected_reference_or_target_splice_denies(which: str, field: str) -> None:
    case = selected_case()
    source = getattr(case.template, which)
    key = (
        "company_id"
        if field == "company_id"
        else ("resource_id" if which == "output_resource" else "artifact_revision_id")
    )
    value = source.model_copy(update={key: UUID(int=999)})
    case = (
        replace(case, source_metadata=value)
        if which == "source_metadata"
        else changed(case, "spec", which, value)
    )
    with pytest.raises(ValueError):
        case.check()


@pytest.mark.parametrize("field", list(BuilderLimits.model_fields))
def test_every_exact_limit_cannot_drift_within_valid_bounds(field: str) -> None:
    case = selected_case()
    limits = case.spec.job.limits.model_copy(
        update={field: getattr(case.spec.job.limits, field) - 1}
    )
    with pytest.raises(ValueError):
        changed(case, "job", "limits", limits).check()


@pytest.mark.parametrize("value", [True, False, 1.0, "1"])
@pytest.mark.parametrize(
    "target", ["spec", "template", "source", "patch", "template_source", "template_patch"]
)
def test_copied_count_types_deny_before_any_serialization(
    value: object, target: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = selected_case()
    if target in {"spec", "template"}:
        limits = case.spec.job.limits.model_copy(update={"command_seconds": value})
        case = (
            changed(case, "job", "limits", limits)
            if target == "spec"
            else changed(case, "template", "limits", limits)
        )
    elif target == "source":
        case = replace(
            case, source_metadata=case.source_metadata.model_copy(update={"byte_length": value})
        )
    elif target == "patch":
        case = changed(
            case,
            "spec",
            "protected_patch",
            case.template.protected_patch.model_copy(update={"byte_length": value}),
        )
    else:
        field = "source_metadata" if target == "template_source" else "protected_patch"
        ref = getattr(case.template, field).model_copy(update={"byte_length": value})
        case = changed(case, "template", field, ref)

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("Raw counts must deny before model_dump")

    monkeypatch.setattr(type(case.spec), "model_dump", forbidden)
    monkeypatch.setattr(type(case.template), "model_dump", forbidden)
    with pytest.raises(ValueError):
        case.check()


@pytest.mark.parametrize(
    "field", ["artifact_id", "artifact_revision_id", "revision", "sha256", "byte_length"]
)
@pytest.mark.parametrize("which", ["source_metadata", "protected_patch"])
def test_every_protected_reference_field_is_exact(field: str, which: str) -> None:
    case = selected_case()
    original = getattr(case.template, which)
    value = (
        UUID(int=999)
        if field.endswith("_id")
        else 401
        if field == "byte_length"
        else "f" * 64
        if field == "sha256"
        else "other-revision"
    )
    ref = original.model_copy(update={field: value})
    case = (
        replace(case, source_metadata=ref)
        if which == "source_metadata"
        else changed(case, "spec", which, ref)
    )
    with pytest.raises(ValueError):
        case.check()


@pytest.mark.parametrize("field", list(BuilderToolPolicy.model_fields))
def test_complete_actual_builder_policy_must_equal_trusted_template(field: str) -> None:
    case = selected_case()
    values: dict[str, object] = {
        "company_id": UUID(int=999),
        "policy_symbol": "other.policy",
        "resource_symbol": "other.resource",
        "repository_symbol": "other.repository",
        "image": "registry.example/other@sha256:" + "f" * 64,
        "commands": (case.policy.commands[0].model_copy(update={"argv": ("/bin/false",)}),),
        "write_paths": ("other",),
        "artifact_paths": ("other",),
        "runtime_inputs": None,
        "runtime_recipe": "nexus.builder.runtime.v1",
        "runtime_method_sha256": "f" * 64,
        "full_execution_method_sha256": "f" * 64,
    }
    policy = case.policy.model_copy(update={field: values[field]})
    spec = case.spec.model_copy(update={"policy_sha256": canonical_sha256(policy)})
    with pytest.raises(ValueError):
        replace(case, policy=policy, spec=spec).check()


def test_job_ordered_commands_and_same_phase_keys_cannot_change() -> None:
    case = selected_case()
    commands = case.spec.job.commands
    for value in ((commands[1], commands[0], *commands[2:]), commands[:-1]):
        with pytest.raises(ValueError):
            changed(case, "job", "commands", value).check()


def test_action_id_is_only_a_description_until_native_journal_is_resolved() -> None:
    case = selected_case()
    changed(case, "job", "action_id", UUID(int=999)).check()


def test_selector_cannot_replace_full_method_even_when_all_declared_values_agree() -> None:
    case = selected_case()
    candidate = case.candidate.model_copy(update={"method_sha256": RUNTIME_V2_METHOD_SHA256})
    policy = case.policy.model_copy(
        update={"full_execution_method_sha256": RUNTIME_V2_METHOD_SHA256}
    )
    cp = case.candidate_policy.model_copy(
        update={"candidates": (candidate, case.candidate_policy.candidates[1])}
    )
    template = case.template.model_copy(
        update={
            "policy": policy,
            "candidate_scope_sha256": canonical_sha256(candidate),
            "candidate_policy_sha256": canonical_sha256(cp),
        }
    )
    spec = case.spec.model_copy(update={"policy_sha256": canonical_sha256(policy)})
    with pytest.raises(ValueError):
        replace(
            case,
            candidate=candidate,
            candidate_policy=cp,
            policy=policy,
            template=template,
            spec=spec,
        ).check()
