"""Wrong-path/receipt/report/witness descriptions cannot qualify CSV behavior."""

from datetime import timedelta

import pytest

from nexus.builder.csv_artifact_loader import actual_csv_behavior
from nexus.builder.csv_source_checks import observed_csv_sources
from nexus.builder.engineering_behavior import check_behavior
from nexus.tests.node_v4_support import described_v4_check


def test_actual_json_and_exact_witness_descriptions_recompute_both_roles() -> None:
    value = described_v4_check()
    results = actual_csv_behavior(value)
    assert len(results) == 2 and len(results[0].cases) == 7
    assert check_behavior(value) == (
        "pass",
        "independent_actual_full_csv_regression_reports_passed",
    )


def test_extraneous_result_cannot_select_verifier_receipt_branch() -> None:
    value = described_v4_check()
    extraneous = value.verifier.model_copy(
        update={"recorded_at": value.verifier.recorded_at + timedelta(seconds=1)}
    )
    with pytest.raises(ValueError, match="exact declared"):
        observed_csv_sources(value, extraneous, value.verifier_witness)


@pytest.mark.parametrize("role", ["author", "verifier"])
def test_crossed_role_witness_cannot_supply_an_exact_pair(role: str) -> None:
    value = described_v4_check()
    result = value.author if role == "author" else value.verifier
    witness = value.verifier_witness if role == "author" else value.author_witness
    with pytest.raises(ValueError, match="exact declared"):
        observed_csv_sources(value, result, witness)


@pytest.mark.parametrize(
    "case",
    [
        "receipt",
        "wrong_path",
        "extra_path",
        "witness_hash",
        "spec",
        "missing_report",
        "report_role",
        "raw_pass",
    ],
)
def test_spliced_receipt_source_witness_or_report_denies(case: str) -> None:
    value = described_v4_check()
    if case == "receipt":
        value = value.model_copy(
            update={
                "verifier_receipt": value.verifier_receipt.model_copy(
                    update={"proposal_hash": "a" * 64}
                )
            }
        )
    if case in {"wrong_path", "extra_path", "witness_hash"}:
        witness = value.verifier_witness
        changes = witness.changes
        if case == "wrong_path":
            changes = (
                changes[0].model_copy(update={"path": "packages/shared/src/foreign.ts"}),
                changes[1],
            )
        if case == "extra_path":
            changes = (
                *changes,
                changes[1].model_copy(update={"path": "packages/shared/src/other.ts"}),
            )
        if case == "witness_hash":
            changes = (changes[0].model_copy(update={"before_sha256": "a" * 64}), changes[1])
        value = value.model_copy(
            update={"verifier_witness": witness.model_copy(update={"changes": changes})}
        )
    if case == "spec":
        value = value.model_copy(
            update={
                "verifier_witness": value.verifier_witness.model_copy(
                    update={"spec_sha256": "a" * 64}
                )
            }
        )
    if case in {"missing_report", "report_role", "raw_pass"}:
        result = value.verifier
        if case == "missing_report":
            artifacts = result.artifacts[:-1]
        if case == "report_role":
            artifacts = (
                *result.artifacts[:-1],
                result.artifacts[0].model_copy(
                    update={
                        "metadata": result.artifacts[0].metadata.model_copy(
                            update={"path": "post/checks/web-vitest.json"}
                        )
                    }
                ),
            )
        if case == "raw_pass":
            artifacts = ()
        value = value.model_copy(
            update={"verifier": result.model_copy(update={"artifacts": artifacts})}
        )
    assert check_behavior(value)[0] == "reject"
