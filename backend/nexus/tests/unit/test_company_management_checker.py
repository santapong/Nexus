"""A real bounded report is checked against exact independent input snapshots.

The single owned test module exceeds the 400-line policy limit because it retains
the complete negative and alternate-value matrix with one shared typed fixture.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from nexus.company.brain.base import SourceTime
from nexus.company.brain.sources import (
    ArtifactRevisionRef,
    EvidenceRecord,
    SourceHead,
    SourceRevisionRef,
    UTF8Span,
)
from nexus.company.contracts.work import WorkItem
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import (
    REPORT_CHECK_CRITERIA,
    REPORT_CHECK_RECIPE,
    CitationCheckSource,
    ReportCheckInput,
    ReportCheckResult,
    ReportCheckSnapshot,
)
from nexus.company.management.operations import LedgerSnapshot, ReportSnapshot, WorkProjection
from nexus.company.management.plans import RunBinding
from nexus.company.management.report_checker import check_internal_report
from nexus.company.management.report_rules import OperatingProjection
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionRegistration
from nexus.execution.runtime_support import registration_digest


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def actual_report() -> ReportCheckInput:
    """An alternate-value source, held ledger and accepted work, never a pass candidate."""
    # The fixture exceeds 50 lines to preserve every exact nested target/source identity.
    company, workspace = uuid4(), uuid4()
    observed = datetime(2026, 10, 14, 12, 31, tzinfo=UTC)
    author = RunBinding(
        company_id=company,
        workspace_id=workspace,
        actor_id=uuid4(),
        task_id=uuid4(),
        trace_id=uuid4(),
        run_id=uuid4(),
        workflow_name="research",
        workflow_version="v7",
        model_profile="offline",
        model_registry_version="models-v3",
    )
    verifier = author.model_copy(
        update={"actor_id": uuid4(), "task_id": uuid4(), "run_id": uuid4()}
    )
    registration = ExecutionRegistration(
        work=WorkItem(
            company_id=company,
            task_id=author.task_id,
            trace_id=author.trace_id,
            goal_id=uuid4(),
            department="research",
            title="Internal source report",
            acceptance=REPORT_CHECK_CRITERIA,
            budget_usd=Decimal("0.9"),
        ),
        run_id=author.run_id,
        workflow_name=author.workflow_name,
        workflow_version=author.workflow_version,
        model_profile=author.model_profile,
        model_registry_version=author.model_registry_version,
        quota=AttemptQuota(),
    )
    accepted_id, unknown_id = uuid4(), uuid4()
    source_text = "กำหนดส่ง: 2027-02; customer count: 43; source-reported only."
    source_raw = source_text.encode()
    source_artifact = ArtifactRevisionRef(
        company_id=company,
        artifact_id=uuid4(),
        artifact_revision_id=uuid4(),
        revision="r2",
        sha256=_digest(source_raw),
        byte_length=len(source_raw),
    )
    source = SourceRevisionRef(
        company_id=company,
        source_id=uuid4(),
        source_revision_id=uuid4(),
        revision="commit-9",
    )
    event = SourceTime(precision="month", value="2027-02", basis="source-declared deadline")
    evidence = EvidenceRecord(
        company_id=company,
        evidence_id=uuid4(),
        source=source,
        artifact=source_artifact,
        raw_span=UTF8Span(start_byte=0, end_byte=len(source_raw)),
        span_sha256=_digest(source_raw),
        source_event=event,
        ingested_at=observed,
    )
    current = SourceHead(
        company_id=company,
        source_id=source.source_id,
        current=source,
        generation=3,
        observed_at=observed,
        fresh_until=observed + timedelta(hours=1),
        availability="available",
    )
    work = WorkProjection(
        company_id=company,
        work=author,
        execution_state="verifying",
        registered_active=False,
        acceptance="accepted",
        acceptance_id=accepted_id,
        billing="unconfirmed",
    )
    report_snapshot = ReportSnapshot(
        company_id=company,
        report_id=uuid4(),
        period_start=observed - timedelta(days=1),
        period_end=observed,
        ledger=LedgerSnapshot(
            held_usd=Decimal("0.317029"),
            spent_usd=Decimal("1.026531"),
            source_sha256="a" * 64,
            observed_at=observed,
        ),
        work=(work,),
        blockers=("Pending invoice",),
        owner_decision_ids=(uuid4(),),
    )
    projection = OperatingProjection(
        company_id=company,
        snapshot=report_snapshot,
        unknown_charge_ids=(unknown_id,),
        actual_total_usd=None,
        accepted_task_ids=(author.task_id,),
        receipt_task_ids=(author.task_id,),
        cancelled_task_ids=(),
    )
    snapshots = ReportCheckSnapshot(
        company_id=company,
        observed_at=observed,
        author_binding=author,
        author_registration=registration,
        author_registration_sha256=registration_digest(registration),
        operating=projection,
        citations=(CitationCheckSource(evidence=evidence, head=current, raw_text=source_text),),
    )
    body = {
        "schema_version": "nexus.company.internal-report.v1",
        "company_id": str(company),
        "operating": projection.model_dump(mode="json"),
        "claims": [
            {
                "kind": "source_quote",
                "evidence_id": str(evidence.evidence_id),
                "source_revision_id": str(source.source_revision_id),
                "artifact_revision_id": str(source_artifact.artifact_revision_id),
                "span_sha256": evidence.span_sha256,
                "quote": source_text,
                "source_event": event.model_dump(),
                "source_state": "current",
                "freshness": "fresh",
            },
            {
                "kind": "accepted_work",
                "task_id": str(author.task_id),
                "acceptance_id": str(accepted_id),
            },
        ],
    }
    raw = json.dumps(body, ensure_ascii=False).encode()
    output = source_artifact.model_copy(
        update={
            "artifact_id": uuid4(),
            "artifact_revision_id": uuid4(),
            "revision": "report-v1",
            "sha256": _digest(raw),
            "byte_length": len(raw),
        }
    )
    target = VerificationSpec(
        company_id=company,
        author=author,
        verifier=verifier,
        action_id=uuid4(),
        proposal_sha256="b" * 64,
        receipt_id=uuid4(),
        receipt_sha256="c" * 64,
        work_snapshot_sha256=registration_digest(registration),
        criterion_ids=REPORT_CHECK_CRITERIA,
        artifacts=(output,),
        check_recipe=REPORT_CHECK_RECIPE,
    )
    return ReportCheckInput(
        company_id=company,
        target=target,
        output=output,
        output_utf8=raw,
        snapshot=snapshots,
    )


def _body(command: ReportCheckInput) -> dict[str, Any]:
    # Test mutation operates on untrusted decoded JSON; production validates the wire model.
    assert command.output_utf8 is not None
    return json.loads(command.output_utf8)  # type: ignore[no-any-return]


def _replace_output(command: ReportCheckInput, body: object) -> ReportCheckInput:
    raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
    output = command.output.model_copy(update={"sha256": _digest(raw), "byte_length": len(raw)})
    return command.model_copy(
        update={
            "output": output,
            "output_utf8": raw,
            "target": command.target.model_copy(update={"artifacts": (output,)}),
        }
    )


def _criterion(command: ReportCheckInput, criterion_id: str) -> str:
    result = check_internal_report(command)
    return next(row.verdict for row in result.criteria if row.criterion_id == criterion_id)


def test_exact_report_passes_and_hashes_bind_every_actual_byte(
    actual_report: ReportCheckInput,
) -> None:
    result = check_internal_report(actual_report)
    assert result.verdict == "pass"
    assert result.target_sha256 == canonical_sha256(actual_report.target)
    assert result.output_sha256 == _digest(actual_report.output_utf8 or b"")
    assert actual_report.snapshot is not None
    assert result.input_snapshot_sha256 == canonical_sha256(actual_report.snapshot)
    assert result.result_sha256 == canonical_sha256(result.payload)
    assert tuple(row.criterion_id for row in result.criteria) == REPORT_CHECK_CRITERIA
    assert all(row.verdict == "pass" for row in result.criteria)


@pytest.mark.parametrize(
    "raw",
    [b"not JSON", b"\xff", b"[]", b"{}", b'{"a":NaN}', b"x" * 262145],
    ids=["non-json", "non-utf8", "array", "missing-schema", "nonfinite", "oversized"],
)
def test_invalid_or_unbounded_report_never_passes(
    actual_report: ReportCheckInput, raw: bytes
) -> None:
    result = check_internal_report(_replace_output(actual_report, raw))
    assert result.verdict == "reject"
    assert _criterion(_replace_output(actual_report, raw), "report.schema.v1") == "reject"


def test_duplicate_json_keys_are_rejected(actual_report: ReportCheckInput) -> None:
    raw = actual_report.output_utf8 or b""
    raw = raw.replace(b'"claims":', b'"claims": [], "claims":', 1)
    assert check_internal_report(_replace_output(actual_report, raw)).verdict == "reject"


@pytest.mark.parametrize("field", ["output_utf8", "snapshot"])
def test_missing_proof_is_explicit_inconclusive(
    actual_report: ReportCheckInput, field: str
) -> None:
    result = check_internal_report(actual_report.model_copy(update={field: None}))
    assert result.verdict == "inconclusive"
    assert all(row.verdict != "pass" for row in result.criteria)


@pytest.mark.parametrize("criterion_ids", [("semantic.customer-ready",), ("report.ledger.v1",)])
def test_unknown_or_incomplete_registry_never_defaults_pass(
    actual_report: ReportCheckInput,
    criterion_ids: tuple[str, ...],
) -> None:
    target = actual_report.target.model_copy(update={"criterion_ids": criterion_ids})
    result = check_internal_report(actual_report.model_copy(update={"target": target}))
    assert result.verdict == "inconclusive"
    assert tuple(row.criterion_id for row in result.criteria) == criterion_ids


def test_unknown_recipe_is_inconclusive(actual_report: ReportCheckInput) -> None:
    target = actual_report.target.model_copy(update={"check_recipe": "unregistered-v2"})
    assert (
        check_internal_report(actual_report.model_copy(update={"target": target})).verdict
        == "inconclusive"
    )


@pytest.mark.parametrize("field", ["output", "snapshot"])
def test_exact_bound_input_hash_tampering_rejects(
    actual_report: ReportCheckInput, field: str
) -> None:
    if field == "output":
        command = actual_report.model_copy(
            update={"output_utf8": (actual_report.output_utf8 or b"") + b" "}
        )
    else:
        assert actual_report.snapshot is not None
        altered = actual_report.snapshot.model_copy(
            update={"observed_at": datetime(2028, 1, 1, tzinfo=UTC)}
        )
        command = actual_report.model_copy(update={"snapshot": altered})
    assert check_internal_report(command).verdict == "reject"


@pytest.mark.parametrize(
    "field,value",
    [
        ("quote", "customer count: 12"),
        ("source_revision_id", str(uuid4())),
        ("artifact_revision_id", str(uuid4())),
        ("span_sha256", "f" * 64),
        ("evidence_id", str(uuid4())),
        ("source_state", "historical"),
        ("freshness", "stale"),
    ],
)
def test_citations_require_exact_actual_source_proof(
    actual_report: ReportCheckInput,
    field: str,
    value: str,
) -> None:
    body = _body(actual_report)
    body["claims"][0][field] = value
    assert _criterion(_replace_output(actual_report, body), "report.citations.v1") != "pass"


def test_source_artifact_bytes_tampering_is_rejected(actual_report: ReportCheckInput) -> None:
    assert actual_report.snapshot is not None
    source = actual_report.snapshot.citations[0].model_copy(update={"raw_text": "wrong source"})
    snapshot = actual_report.snapshot.model_copy(update={"citations": (source,)})
    target = actual_report.target.model_copy(
        update={"work_snapshot_sha256": canonical_sha256(snapshot)}
    )
    command = actual_report.model_copy(update={"snapshot": snapshot, "target": target})
    assert _criterion(command, "report.citations.v1") == "reject"


@pytest.mark.parametrize(
    "time",
    [
        {"precision": "day", "value": "2027-02-01", "basis": "source-declared deadline"},
        {"precision": "month", "value": "2027-03", "basis": "source-declared deadline"},
        {"precision": "month", "value": "2027-02", "basis": "guessed"},
    ],
)
def test_date_and_precision_are_not_invented(actual_report: ReportCheckInput, time: object) -> None:
    body = _body(actual_report)
    body["claims"][0]["source_event"] = time
    assert _criterion(_replace_output(actual_report, body), "report.source-time.v1") == "reject"


def test_uncheckable_semantic_claim_is_inconclusive(actual_report: ReportCheckInput) -> None:
    body = _body(actual_report)
    body["claims"].append({"kind": "semantic", "text": "StockFlow is ready for customers"})
    command = _replace_output(actual_report, body)
    assert _criterion(command, "report.claim-basis.v1") == "inconclusive"
    assert check_internal_report(command).verdict == "inconclusive"


def test_distinct_verifier_does_not_prove_author_acceptance(
    actual_report: ReportCheckInput,
) -> None:
    body = _body(actual_report)
    body["claims"][1]["acceptance_id"] = str(uuid4())
    assert _criterion(_replace_output(actual_report, body), "report.claim-basis.v1") == "reject"


@pytest.mark.parametrize(
    "field,value",
    [
        ("actual_total_usd", "0.000000"),
        ("unknown_charge_ids", []),
    ],
)
def test_unknown_billing_is_not_zero_or_omitted(
    actual_report: ReportCheckInput,
    field: str,
    value: object,
) -> None:
    body = _body(actual_report)
    body["operating"][field] = value
    assert _criterion(_replace_output(actual_report, body), "report.ledger.v1") == "reject"


def test_ancestor_and_child_ledger_double_counting_rejects(actual_report: ReportCheckInput) -> None:
    body = _body(actual_report)
    body["operating"]["snapshot"]["ledger"]["spent_usd"] = "2.053062"
    assert _criterion(_replace_output(actual_report, body), "report.ledger.v1") == "reject"


@pytest.mark.parametrize(
    "field,value",
    [
        ("registered_active", True),
        ("acceptance", "pending"),
        ("billing", "known"),
        ("execution_state", "completed"),
    ],
)
def test_status_cannot_hide_inactive_unknown_or_invent_completion(
    actual_report: ReportCheckInput,
    field: str,
    value: object,
) -> None:
    body = _body(actual_report)
    body["operating"]["snapshot"]["work"][0][field] = value
    assert check_internal_report(_replace_output(actual_report, body)).verdict == "reject"


def test_blockers_decisions_and_work_cannot_be_omitted(actual_report: ReportCheckInput) -> None:
    body = _body(actual_report)
    body["operating"]["snapshot"]["blockers"] = []
    body["operating"]["snapshot"]["owner_decision_ids"] = []
    body["operating"]["snapshot"]["work"] = []
    assert _criterion(_replace_output(actual_report, body), "report.status.v1") == "reject"


@pytest.mark.parametrize(
    "precision,value",
    [("unknown", None), ("year", "2029"), ("instant", "2025-04-03T10:11:12+07:00")],
)
def test_exact_alternate_time_precision_passes_without_normalization(
    actual_report: ReportCheckInput,
    precision: str,
    value: str | None,
) -> None:
    assert actual_report.snapshot is not None
    time = SourceTime.model_validate_json(
        json.dumps(
            {
                "precision": precision,
                "value": value,
                "basis": "explicit supplied source time",
            }
        )
    )
    original = actual_report.snapshot.citations[0]
    evidence = original.evidence.model_copy(update={"source_event": time})
    snapshot = actual_report.snapshot.model_copy(
        update={
            "citations": (original.model_copy(update={"evidence": evidence}),),
        }
    )
    body = _body(actual_report)
    body["claims"][0]["source_event"] = time.model_dump(mode="json")
    command = actual_report.model_copy(update={"snapshot": snapshot})
    assert check_internal_report(_replace_output(command, body)).verdict == "pass"


def test_explicit_historical_stale_source_preserves_labels(actual_report: ReportCheckInput) -> None:
    assert actual_report.snapshot is not None
    original = actual_report.snapshot.citations[0]
    head = original.head.model_copy(
        update={
            "current": original.head.current.model_copy(update={"source_revision_id": uuid4()}),
            "fresh_until": None,
        }
    )
    snapshot = actual_report.snapshot.model_copy(
        update={
            "citations": (original.model_copy(update={"head": head}),),
        }
    )
    body = _body(actual_report)
    body["claims"][0].update({"source_state": "historical", "freshness": "stale"})
    command = actual_report.model_copy(update={"snapshot": snapshot})
    assert check_internal_report(_replace_output(command, body)).verdict == "pass"


def test_missing_operating_snapshot_is_inconclusive(actual_report: ReportCheckInput) -> None:
    assert actual_report.snapshot is not None
    snapshot = actual_report.snapshot.model_copy(update={"operating": None})
    command = actual_report.model_copy(update={"snapshot": snapshot})
    assert check_internal_report(command).verdict == "inconclusive"


@pytest.mark.parametrize(
    "unknown", ["unknown_charge_ids", "accepted_task_ids", "receipt_task_ids", "cancelled_task_ids"]
)
def test_fabricated_or_duplicated_operating_identity_never_passes(
    actual_report: ReportCheckInput, unknown: str
) -> None:
    body = _body(actual_report)
    values = body["operating"][unknown]
    body["operating"][unknown] = values * 2 if values else [str(uuid4()), str(uuid4())]
    assert check_internal_report(_replace_output(actual_report, body)).verdict == "reject"


@pytest.mark.parametrize("amount", ["0.000000", "3.289451"])
def test_exact_known_billing_including_actual_zero_passes(
    actual_report: ReportCheckInput,
    amount: str,
) -> None:
    assert actual_report.snapshot is not None and actual_report.snapshot.operating is not None
    expected = actual_report.snapshot.operating
    work = expected.snapshot.work[0].model_copy(update={"billing": "known"})
    ledger = expected.snapshot.ledger.model_copy(update={"spent_usd": Decimal(amount)})
    report_snapshot = expected.snapshot.model_copy(update={"work": (work,), "ledger": ledger})
    operating = expected.model_copy(
        update={
            "snapshot": report_snapshot,
            "actual_total_usd": Decimal(amount),
            "unknown_charge_ids": (),
        }
    )
    snapshot = actual_report.snapshot.model_copy(update={"operating": operating})
    body = _body(actual_report)
    body["operating"] = operating.model_dump(mode="json")
    command = actual_report.model_copy(update={"snapshot": snapshot})
    assert check_internal_report(_replace_output(command, body)).verdict == "pass"


@pytest.mark.parametrize("field,value", [("result_sha256", "d" * 64), ("verdict", "reject")])
def test_decoded_checker_result_rejects_tampering(
    actual_report: ReportCheckInput,
    field: str,
    value: str,
) -> None:
    body = check_internal_report(actual_report).model_dump(mode="json")
    body[field] = value
    with pytest.raises(ValidationError):
        ReportCheckResult.model_validate_json(json.dumps(body))


def test_result_is_deterministic_without_new_authority(actual_report: ReportCheckInput) -> None:
    first, second = check_internal_report(actual_report), check_internal_report(actual_report)
    assert first == second
    assert "no_semantic_truth_or_acceptance_authority" in first.limitations


def test_input_snapshot_hash_cannot_replace_actual_work_registration(
    actual_report: ReportCheckInput,
) -> None:
    assert actual_report.snapshot is not None
    target = actual_report.target.model_copy(
        update={
            "work_snapshot_sha256": canonical_sha256(actual_report.snapshot),
        }
    )
    command = actual_report.model_copy(update={"target": target})
    result = check_internal_report(command)
    assert result.verdict == "reject"
    assert result.input_snapshot_sha256 == canonical_sha256(actual_report.snapshot)


@pytest.mark.parametrize("change", ["row_hash", "run", "criteria", "author"])
def test_actual_registration_criteria_and_author_binding_are_exact(
    actual_report: ReportCheckInput,
    change: str,
) -> None:
    assert actual_report.snapshot is not None
    snapshot = actual_report.snapshot
    if change == "row_hash":
        snapshot = snapshot.model_copy(update={"author_registration_sha256": "e" * 64})
    elif change == "author":
        snapshot = snapshot.model_copy(
            update={
                "author_binding": snapshot.author_binding.model_copy(update={"actor_id": uuid4()}),
            }
        )
    else:
        registration = snapshot.author_registration
        if change == "run":
            registration = registration.model_copy(update={"run_id": uuid4()})
        else:
            work = registration.work.model_copy(update={"acceptance": ("arbitrary-semantic",)})
            registration = registration.model_copy(update={"work": work})
        snapshot = snapshot.model_copy(update={"author_registration": registration})
    assert (
        check_internal_report(actual_report.model_copy(update={"snapshot": snapshot})).verdict
        == "reject"
    )
