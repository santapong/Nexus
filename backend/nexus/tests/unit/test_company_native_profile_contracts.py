"""Profile selectors cannot invent schedules, authority or a mutable evidence set."""

from uuid import uuid4

import pytest

from nexus.company.management.commitment_contracts import CommitmentRevisionRef
from nexus.company.management.native_profile_contracts import NativeReportProfileRef


def profile() -> NativeReportProfileRef:
    company = uuid4()
    return NativeReportProfileRef(
        company_id=company,
        report_id=uuid4(),
        report_sha256="a" * 64,
        selection_sha256="b" * 64,
        commitment=CommitmentRevisionRef(
            company_id=company,
            commitment_id=uuid4(),
            revision_id=uuid4(),
            version="v1",
            sha256="c" * 64,
        ),
        evidence_ids=(uuid4(),),
    )


@pytest.mark.parametrize(
    "field", ["owner_id", "actor_id", "due_at", "approved", "budget_usd", "profile_path"]
)
def test_profile_ref_contains_no_owner_clock_permission_or_path_override(field: str) -> None:
    values = profile().model_dump()
    values[field] = True
    with pytest.raises(ValueError):
        NativeReportProfileRef.model_validate(values)


@pytest.mark.parametrize("kind", ["empty", "duplicate", "too_many", "foreign", "bad_hash"])
def test_profile_ref_requires_exact_bounded_native_identities(kind: str) -> None:
    record = profile()
    values = record.model_dump()
    if kind == "empty":
        values["evidence_ids"] = ()
    elif kind == "duplicate":
        values["evidence_ids"] = (record.evidence_ids[0], record.evidence_ids[0])
    elif kind == "too_many":
        values["evidence_ids"] = tuple(uuid4() for _ in range(33))
    elif kind == "foreign":
        values["commitment"] = record.commitment.model_copy(update={"company_id": uuid4()})
    else:
        values["report_sha256"] = "claimed"
    with pytest.raises(ValueError):
        NativeReportProfileRef.model_validate(values)


def test_profile_ref_json_roundtrip_retains_order_and_exact_hashes() -> None:
    record = profile()
    assert NativeReportProfileRef.model_validate_json(record.model_dump_json()) == record
