"""Protected report bytes select bounded exact inputs, never caller source text."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

import pytest

from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.management.check_contracts import ReportCheckInput
from nexus.company.management.report_input_sources import report_request
from nexus.tests.unit.test_company_management_checker import actual_report as actual_report


def test_exact_report_selects_only_declared_quote_ids(actual_report: ReportCheckInput) -> None:
    assert actual_report.output_utf8 is not None and actual_report.snapshot is not None
    report, ids = report_request(
        actual_report.target, actual_report.output, actual_report.output_utf8
    )
    assert report.company_id == actual_report.company_id
    assert ids == tuple(row.evidence.evidence_id for row in actual_report.snapshot.citations)


@pytest.mark.parametrize("change", ["company", "extra_output", "wrong_output", "recipe", "bytes"])
def test_report_selection_denies_spliced_or_unbounded_input(
    actual_report: ReportCheckInput, change: str
) -> None:
    assert actual_report.output_utf8 is not None
    target, output, raw = actual_report.target, actual_report.output, actual_report.output_utf8
    if change == "company":
        target = target.model_copy(update={"company_id": uuid4()})
    elif change == "extra_output":
        target = target.model_copy(update={"artifacts": (output, output)})
    elif change == "wrong_output":
        output = output.model_copy(update={"artifact_revision_id": uuid4()})
    elif change == "recipe":
        target = target.model_copy(update={"check_recipe": "unknown-check"})
    else:
        raw = b"x" * 262_145
    with pytest.raises(AcceptanceDeniedError):
        report_request(target, output, raw)


@pytest.mark.parametrize(
    "change", ["duplicate_key", "duplicate_citation", "foreign_report", "malformed"]
)
def test_report_json_cannot_choose_conflicting_sources(
    actual_report: ReportCheckInput, change: str
) -> None:
    assert actual_report.output_utf8 is not None
    data = json.loads(actual_report.output_utf8)
    if change == "duplicate_key":
        raw = (
            actual_report.output_utf8[:-1]
            + b',"company_id":"'
            + str(data["company_id"]).encode()
            + b'"}'
        )
    elif change == "duplicate_citation":
        data["claims"].append(data["claims"][0])
        raw = json.dumps(data).encode()
    elif change == "foreign_report":
        data["company_id"] = str(uuid4())
        raw = json.dumps(data).encode()
    else:
        raw = b"{broken"
    output = ArtifactRevisionRef(
        **actual_report.output.model_dump(exclude={"sha256", "byte_length"}),
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
    )
    target = actual_report.target.model_copy(update={"artifacts": (output,)})
    with pytest.raises(AcceptanceDeniedError):
        report_request(target, output, raw)


@pytest.mark.parametrize(
    "change",
    [None, "task_id", "trace_id", "run_id", "workflow_version", "model_registry_version", "hash"],
)
def test_native_author_recomputes_exact_m1_registration(
    actual_report: ReportCheckInput, change: str | None
) -> None:
    from nexus.company.management.report_inputs import native_author
    from nexus.execution.runtime_models import ExecutionWork

    assert actual_report.snapshot is not None
    binding, registration = (
        actual_report.snapshot.author_binding,
        actual_report.snapshot.author_registration,
    )
    values = binding.model_dump(exclude={"schema_version"})
    row = ExecutionWork(
        **values,
        registration_json=registration.model_dump_json(),
        registration_hash=actual_report.snapshot.author_registration_sha256,
    )
    if change is None:
        assert native_author(row) == (binding, registration)
        return
    setattr(
        row,
        "registration_hash" if change == "hash" else change,
        "0" * 64 if change == "hash" else (uuid4() if change.endswith("_id") else "other"),
    )
    with pytest.raises(AcceptanceDeniedError):
        native_author(row)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [None, "provenance", "bytes", "offset", "oversize"])
async def test_complete_utf8_read_rechecks_pages_and_full_reference(
    actual_report: ReportCheckInput, change: str | None
) -> None:
    from nexus.company.access import VerifiedIdentity
    from nexus.company.brain.access_contracts import ResourceGeneration
    from nexus.company.brain.artifact_contracts import ArtifactSlice
    from nexus.company.brain.base import BrainReadScope
    from nexus.company.brain.sources import UTF8Span
    from nexus.company.management.report_input_sources import protected_bytes

    assert actual_report.snapshot is not None
    source = actual_report.snapshot.citations[0]
    raw = ("เริ่มต้น " * 4000).encode()
    reference = source.evidence.artifact.model_copy(
        update={"sha256": hashlib.sha256(raw).hexdigest(), "byte_length": len(raw)}
    )
    principal, workspace = uuid4(), uuid4()
    scope = BrainReadScope(
        company_id=actual_report.company_id,
        workspace_id=workspace,
        principal_id=principal,
        operation_id=uuid4(),
        trace_id=uuid4(),
    )
    resource_id = uuid4()

    class Pages:
        calls = 0

        async def bounded_artifact(
            self,
            scope: BrainReadScope,
            identity: VerifiedIdentity,
            artifact_revision_id: UUID,
            *,
            start_byte: int,
            max_bytes: int,
            include_history: bool,
        ) -> ArtifactSlice:
            self.calls += 1
            data = raw[start_byte : start_byte + max_bytes]
            while True:
                try:
                    value = data.decode()
                    break
                except UnicodeDecodeError:
                    data = data[:-1]
            if change == "bytes" and self.calls == 2:
                value = "x" * len(data)
            result = ArtifactSlice(
                company_id=scope.company_id,
                artifact=reference,
                span=UTF8Span(start_byte=start_byte, end_byte=start_byte + len(value.encode())),
                span_sha256=hashlib.sha256(value.encode()).hexdigest(),
                text=value,
                source_contributors=(source.evidence.source,),
                contributors=(
                    ResourceGeneration(
                        company_id=scope.company_id,
                        resource_id=resource_id,
                        generation=2 if change == "provenance" and self.calls == 2 else 1,
                    ),
                ),
                source_heads=(source.head,),
                data_classification="internal",
                source_state="current",
                has_more=start_byte + len(value.encode()) < len(raw),
            )
            return (
                result.model_copy(
                    update={"span": result.span.model_copy(update={"start_byte": start_byte + 1})}
                )
                if change == "offset"
                else result
            )

    reader = Pages()
    identity = VerifiedIdentity(principal_id=principal, workspace_id=workspace)
    if change is None:
        assert await protected_bytes(reader, scope, identity, reference, max_bytes=len(raw)) == raw
        assert reader.calls > 1
    else:
        with pytest.raises(AcceptanceDeniedError):
            await protected_bytes(
                reader,
                scope,
                identity,
                reference,
                max_bytes=len(raw) - 1 if change == "oversize" else len(raw),
            )
        if change == "oversize":
            assert reader.calls == 0
