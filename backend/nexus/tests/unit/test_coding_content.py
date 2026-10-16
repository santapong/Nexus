"""Pure content/real patch checks; supplied metadata is not native qualification.

The cohesive >400-line test exception keeps one source/context fixture with its real
parser, gateway-byte and charged-denial checks; no second fixture layer is needed.
"""

import hashlib
import json
from decimal import Decimal
from typing import cast
from unittest.mock import patch
from uuid import UUID

import pytest
from jsonschema.exceptions import ValidationError as SchemaValidationError

from nexus.builder.contracts import BuilderArtifact, RepositoryPin
from nexus.builder.patch_text import apply_text
from nexus.company.brain.context import ContextManifest
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_content import (
    CodeChangeContent,
    CodingAttempt,
    CodingBinding,
    CodingCandidate,
    coding_annotation,
    coding_schema,
    validate_code_change,
)
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.core.llm.company_adapter_contracts import CompanyModelResult
from nexus.core.llm.company_pricing import TokenUsage
from nexus.harness.model_authorizer import RecordedModelOutcome
from nexus.harness.model_client_contracts import GovernedModelResult
from nexus.tests.unit.test_company_planning_intent import prepared_inputs

PATCH = (
    "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n"
    "@@ -1 +1 @@\n-old\n+new\n"
)


def inputs() -> tuple[CodingBinding, ContextManifest, dict[str, bytes], CodeChangeContent]:
    _, context, planning, scope, _, lease = prepared_inputs()
    original = {"src/app.py": b"old\n", "tests/test_app.py": b"pinned verifier\n"}
    binding = CodingBinding(
        goal=planning.goal,
        plan=PlanRevisionRef(
            company_id=scope.company_id,
            plan_id=UUID(int=22),
            plan_revision_id=UUID(int=23),
            revision=1,
            sha256="b" * 64,
        ),
        task_id=lease.task_id,
        trace_id=lease.trace_id,
        run_id=lease.run_id,
        actor_id=lease.actor_id,
        workspace_id=lease.workspace_id,
        source=RepositoryPin(
            repository_symbol="nexus", commit="a" * 40, tree="b" * 40, archive_sha256="c" * 64
        ),
        source_files=tuple(
            BuilderArtifact(path=path, sha256=hashlib.sha256(raw).hexdigest(), byte_length=len(raw))
            for path, raw in original.items()
        ),
        allowed_write_paths=("src/app.py",),
        context_manifest_sha256=canonical_sha256(context.manifest),
    )
    content = CodeChangeContent(
        patch=PATCH,
        explanation="Correct the demonstrated behavior.",
        questions=(),
        evidence_ids=(context.manifest.inclusions[0].handle.evidence_id,),
    )
    return binding, context.manifest, original, content


def test_closed_schema_actual_parser_and_complete_original_source() -> None:
    binding, manifest, originals, content = inputs()
    schema = coding_schema(binding, manifest=manifest)
    parsed = CodeChangeContent.model_validate_json(
        schema.validate_output(content.model_dump_json())
    )
    changes = validate_code_change(parsed, binding, manifest=manifest, originals=originals)
    assert apply_text(originals[changes[0].path], changes[0]) == b"new\n"
    assert originals["src/app.py"] == b"old\n"
    assert originals["tests/test_app.py"] == b"pinned verifier\n"
    assert coding_annotation(schema) == (binding, manifest)
    assert set(CodeChangeContent.model_fields) == {
        "patch",
        "explanation",
        "questions",
        "evidence_ids",
    }


@pytest.mark.parametrize(
    "field", ["actor_id", "commands", "url", "budget_usd", "approved", "write_paths"]
)
def test_model_fields_cannot_grant_authority(field: str) -> None:
    binding, manifest, _, content = inputs()
    raw = json.dumps(content.model_dump(mode="json") | {field: "model-selected"})
    with pytest.raises(SchemaValidationError):
        coding_schema(binding, manifest=manifest).validate_output(raw)
    with pytest.raises(ValueError):
        CodeChangeContent.model_validate_json(raw)


@pytest.mark.parametrize("field", ["patch", "explanation", "questions", "evidence_ids"])
def test_every_output_field_is_required(field: str) -> None:
    binding, manifest, _, content = inputs()
    raw = content.model_dump(mode="json")
    del raw[field]
    with pytest.raises(SchemaValidationError):
        coding_schema(binding, manifest=manifest).validate_output(json.dumps(raw))


@pytest.mark.parametrize("field", ["questions", "evidence_ids"])
def test_duplicate_entries_denied(field: str) -> None:
    _, _, _, content = inputs()
    value = content.model_dump(mode="json")
    value[field] = ["Repeated?", "Repeated?"] if field == "questions" else [str(UUID(int=1))] * 2
    with pytest.raises(ValueError):
        CodeChangeContent.model_validate_json(json.dumps(value))


@pytest.mark.parametrize(
    "patch",
    [
        "",
        " ",
        "not a patch",
        PATCH.replace("-old", "-wrong"),
        PATCH.replace("@@ -1 +1 @@", "@@ -2 +1 @@"),
        PATCH + PATCH,
        PATCH.replace("+new", "+\x00"),
    ],
)
def test_empty_malformed_duplicate_or_wrong_context_patch_denied(patch: str) -> None:
    binding, manifest, originals, content = inputs()
    with pytest.raises(ValueError):
        validate_code_change(
            content.model_copy(update={"patch": patch}),
            binding,
            manifest=manifest,
            originals=originals,
        )


@pytest.mark.parametrize(
    "path",
    ["../escape.py", "/absolute.py", ".git/config", ".env", "tests/test_app.py", "src/extra.py"],
)
def test_patch_cannot_escape_or_select_undeclared_or_readonly_source(path: str) -> None:
    binding, manifest, originals, content = inputs()
    patch = PATCH.replace("src/app.py", path)
    with pytest.raises(ValueError):
        validate_code_change(
            content.model_copy(update={"patch": patch}),
            binding,
            manifest=manifest,
            originals=originals,
        )


@pytest.mark.parametrize("operation", ["create", "delete"])
def test_first_profile_cannot_add_or_delete_even_a_permitted_path(operation: str) -> None:
    binding, manifest, originals, content = inputs()
    if operation == "create":
        patch = (
            "diff --git a/src/app.py b/src/app.py\nnew file mode 100644\n"
            "--- /dev/null\n+++ b/src/app.py\n@@ -0,0 +1 @@\n+new\n"
        )
    else:
        patch = (
            "diff --git a/src/app.py b/src/app.py\ndeleted file mode 100644\n"
            "--- a/src/app.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n"
        )
    with pytest.raises(ValueError):
        validate_code_change(
            content.model_copy(update={"patch": patch}),
            binding,
            manifest=manifest,
            originals=originals,
        )


@pytest.mark.parametrize("change", ["missing", "extra", "hash", "non-utf8", "nonbytes"])
def test_complete_source_closure_and_actual_bytes_required(change: str) -> None:
    binding, manifest, originals, content = inputs()
    if change == "missing":
        del originals["tests/test_app.py"]
    elif change == "extra":
        originals["extra.py"] = b"uncommitted"
    else:
        originals["tests/test_app.py"] = cast(
            bytes,
            {"hash": b"changed", "non-utf8": b"\xff", "nonbytes": bytearray(b"pinned verifier\n")}[
                change
            ],
        )
        if change == "non-utf8":
            binding = binding.model_copy(
                update={
                    "source_files": (
                        binding.source_files[0],
                        BuilderArtifact(
                            path="tests/test_app.py",
                            byte_length=1,
                            sha256=hashlib.sha256(b"\xff").hexdigest(),
                        ),
                    )
                }
            )
    with pytest.raises(ValueError):
        validate_code_change(content, binding, manifest=manifest, originals=originals)


def test_source_length_mismatch_denies_before_hashing_unbounded_caller_bytes() -> None:
    binding, manifest, originals, content = inputs()
    oversized = b"x" * 65_537
    originals["tests/test_app.py"] = oversized
    with (
        patch(
            "nexus.company.management.coding_content.hashlib.sha256", wraps=hashlib.sha256
        ) as read,
        pytest.raises(ValueError),
    ):
        validate_code_change(content, binding, manifest=manifest, originals=originals)
    assert all(call.args != (oversized,) for call in read.call_args_list)


@pytest.mark.parametrize(
    "change", ["company", "task", "trace", "actor", "hash", "foreign-evidence"]
)
def test_context_original_binding_and_citations_cannot_be_spliced(change: str) -> None:
    binding, manifest, originals, content = inputs()
    if change == "company":
        manifest = manifest.model_copy(update={"company_id": UUID(int=99)})
    elif change in {"task", "trace", "actor"}:
        field = {"task": "task_id", "trace": "task_trace_id", "actor": "actor_id"}[change]
        manifest = manifest.model_copy(update={field: UUID(int=99)})
        binding = binding.model_copy(update={"context_manifest_sha256": canonical_sha256(manifest)})
    elif change == "hash":
        binding = binding.model_copy(update={"context_manifest_sha256": "f" * 64})
    else:
        content = content.model_copy(update={"evidence_ids": (UUID(int=99),)})
    with pytest.raises(ValueError):
        validate_code_change(content, binding, manifest=manifest, originals=originals)


@pytest.mark.parametrize(
    "change", ["duplicate-source", "duplicate-write", "unlisted-write", "foreign-plan"]
)
def test_unchecked_binding_copy_is_revalidated_at_public_entry(change: str) -> None:
    binding, manifest, originals, content = inputs()
    if change == "duplicate-source":
        binding = binding.model_copy(update={"source_files": binding.source_files * 2})
    elif change == "duplicate-write":
        binding = binding.model_copy(
            update={"allowed_write_paths": binding.allowed_write_paths * 2}
        )
    elif change == "unlisted-write":
        binding = binding.model_copy(update={"allowed_write_paths": ("src",)})
    else:
        binding = binding.model_copy(
            update={"plan": binding.plan.model_copy(update={"company_id": UUID(int=99)})}
        )
    with pytest.raises(ValueError):
        validate_code_change(content, binding, manifest=manifest, originals=originals)


def test_utf8_patch_limit_is_exact_and_distinct_from_gateway_json_expansion() -> None:
    binding, manifest, originals, content = inputs()
    overhead = len(PATCH.encode()) - 3
    valid_patch = PATCH.replace("new", "x" * (32768 - overhead))
    exact = content.model_copy(update={"patch": valid_patch})
    assert len(exact.patch.encode()) == 32768
    validate_code_change(exact, binding, manifest=manifest, originals=originals)
    for too_large in [valid_patch.replace("+x", "+xx", 1), PATCH.replace("new", "ก" * 11000)]:
        with pytest.raises(ValueError):
            validate_code_change(
                content.model_copy(update={"patch": too_large}),
                binding,
                manifest=manifest,
                originals=originals,
            )
    expanded = content.model_copy(
        update={
            "explanation": "ก" * 2700,
            "questions": tuple(str(index) + "\x01" * 1000 for index in range(10)),
        }
    )
    assert len(expanded.explanation.encode()) <= 8192
    with pytest.raises(ValueError):
        validate_code_change(expanded, binding, manifest=manifest, originals=originals)


@pytest.mark.parametrize(
    "change", ["source", "goal", "manifest", "annotation-extra", "schema-extra"]
)
def test_exact_annotation_rejects_crossed_server_inputs_or_schema(change: str) -> None:
    binding, manifest, _, _ = inputs()
    document = json.loads(coding_schema(binding, manifest=manifest).document)
    annotation = json.loads(document["$comment"])
    if change == "source":
        annotation["binding"]["source"]["commit"] = "f" * 40
    elif change == "goal":
        annotation["binding"]["goal"]["revision_id"] = str(UUID(int=99))
    elif change == "manifest":
        annotation["context_manifest"]["prompt_sha256"] = "e" * 64
    elif change == "annotation-extra":
        annotation["approved"] = True
    else:
        document["properties"]["approved"] = {"type": "boolean"}
    document["$comment"] = json.dumps(annotation)
    from nexus.core.llm.company_adapter_contracts import JsonSchemaDocument

    with pytest.raises(ValueError):
        coding_annotation(JsonSchemaDocument(schema_json=json.dumps(document)))


def recorded_case() -> tuple[CodingCandidate, GovernedModelResult]:
    binding, manifest, _, content = inputs()
    artifact = ArtifactRef(
        company_id=binding.goal.company_id,
        artifact_id=UUID(int=31),
        reference="model-result-envelope:fixture",
        revision="model-result-envelope-v1",
        sha256="d" * 64,
        allowed_principals=(binding.actor_id,),
    )
    candidate = CodingCandidate(
        binding=binding,
        manifest=manifest,
        request_id=UUID(int=32),
        action_id=UUID(int=33),
        request_sha256="a" * 64,
        action_proposal_sha256="b" * 64,
        content=content,
        artifact=artifact,
        receipt_id=UUID(int=34),
    )
    result = CompanyModelResult(
        request_id=candidate.request_id,
        status="response",
        billing="known",
        usage=TokenUsage(
            input_tokens=100, output_tokens=200, cached_input_tokens=0, reasoning_tokens=0
        ),
        structured_json=content.model_dump_json(),
    )
    recorded = RecordedModelOutcome(
        artifact=artifact,
        billing="known",
        actual_usd=Decimal("0.012345"),
        stop_required=False,
        receipt_id=candidate.receipt_id,
    )
    governed = GovernedModelResult(
        provider_result=result,
        recorded=recorded,
        recording_status="recorded",
        ledger_billing="known",
        billing_limitation="none",
        release_status="released",
        execution_state="verifying",
        stop_required=False,
    )
    return candidate, governed


def test_candidate_is_historical_and_domain_denial_preserves_actual_known_charge() -> None:
    candidate, governed = recorded_case()
    accepted = CodingAttempt(
        governed=governed, candidate=candidate, denial=None, stop_required=False
    )
    assert accepted.candidate is not None and accepted.candidate.status == "historical_candidate"
    assert not accepted.company_completed
    denied = CodingAttempt(governed=governed, candidate=None, denial="invalid_content")
    assert denied.governed.recorded is governed.recorded
    assert denied.governed.recorded is not None
    assert denied.governed.recorded.actual_usd == Decimal("0.012345")
    assert denied.stop_required and denied.governed.ledger_billing == "known"


@pytest.mark.parametrize(
    "change",
    ["failed", "unknown", "cancelled", "unreleased", "receipt", "artifact", "content", "request"],
)
def test_candidate_never_upgrades_failure_unknown_or_spliced_provenance(change: str) -> None:
    candidate, governed = recorded_case()
    recorded = governed.recorded
    assert recorded is not None
    if change in {"failed", "cancelled"}:
        governed = governed.model_copy(
            update={
                "provider_result": governed.provider_result.model_copy(
                    update={"status": change, "structured_json": None}
                ),
                "stop_required": True,
                "recorded": recorded.model_copy(update={"stop_required": True}),
            }
        )
    elif change == "unknown":
        governed = governed.model_copy(
            update={
                "provider_result": CompanyModelResult(
                    request_id=candidate.request_id,
                    status="failed",
                    billing="unknown",
                    error_code="usage_unavailable",
                ),
                "recorded": recorded.model_copy(
                    update={
                        "billing": "unknown",
                        "actual_usd": None,
                        "receipt_id": None,
                        "stop_required": True,
                    }
                ),
                "ledger_billing": "unknown",
                "billing_limitation": "unreconciled_hold",
                "stop_required": True,
            }
        )
    elif change == "unreleased":
        governed = governed.model_copy(
            update={
                "release_status": "failed",
                "release_error": "release_denied",
                "execution_state": None,
                "stop_required": True,
            }
        )
    elif change == "receipt":
        candidate = candidate.model_copy(update={"receipt_id": UUID(int=99)})
    elif change == "artifact":
        candidate = candidate.model_copy(
            update={"artifact": candidate.artifact.model_copy(update={"sha256": "f" * 64})}
        )
    elif change == "request":
        candidate = candidate.model_copy(update={"request_id": UUID(int=99)})
    else:
        candidate = candidate.model_copy(
            update={"content": candidate.content.model_copy(update={"explanation": "Other"})}
        )
    with pytest.raises(ValueError):
        CodingAttempt(governed=governed, candidate=candidate, denial=None, stop_required=False)
    if change in {"failed", "cancelled", "unknown"}:
        denied = CodingAttempt(governed=governed, candidate=None, denial="model_outcome")
        assert denied.governed.provider_result == governed.provider_result
        assert denied.governed.recorded == governed.recorded
