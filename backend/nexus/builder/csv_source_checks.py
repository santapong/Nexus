"""Exact receipt-backed native witness digests; expected pins alone prove no observation."""

from __future__ import annotations

from typing import Literal

from nexus.builder.csv_report_contracts import CsvObservedSources, CsvRegressionPins
from nexus.builder.engineering_contracts import EngineeringCheckInput, EngineeringSourceWitness
from nexus.builder.execution_contracts import BuilderRunResult
from nexus.builder.node_v4_recipe import require_v4_recipe
from nexus.company.management.canonical import canonical_sha256

MODULE = "packages/shared/src/csv/index.ts"
TEST = "packages/shared/src/csv/csv.test.ts"


def observed_csv_sources(
    value: EngineeringCheckInput, result: BuilderRunResult, witness: EngineeringSourceWitness
) -> CsvObservedSources:
    """Caller must first materialize actual licensed public native receipts/protected results."""
    if (result, witness) == (value.author, value.author_witness):
        role: Literal["author", "verifier"] = "author"
    elif (result, witness) == (value.verifier, value.verifier_witness):
        role = "verifier"
    else:
        raise ValueError("CSV result/witness must be an exact declared author or verifier pair")
    pins = value.declaration.csv_regression
    if pins is None:
        raise ValueError("CSV source qualifier requires a reviewed declaration")
    require_v4_recipe(result.spec, value.declaration.policy)
    runtime = result.spec.runtime_inputs
    if runtime is None or runtime.csv_regression != pins:
        raise ValueError("Actual native CSV runtime pins differ from declaration")
    if result.outcome != "commands_succeeded" or witness.spec_sha256 != canonical_sha256(
        result.spec
    ):
        raise ValueError("CSV source witness binds another native result")
    _receipt_binding(value, result, role)
    if (witness.source, witness.patch_sha256) != (
        result.spec.job.source,
        result.spec.job.patch_sha256,
    ):
        raise ValueError("CSV source witness differs from native source/patch")
    return _changed_sources(pins, witness)


def _changed_sources(
    pins: CsvRegressionPins, witness: EngineeringSourceWitness
) -> CsvObservedSources:
    if tuple(row.path for row in witness.changes) != tuple(sorted((MODULE, TEST))):
        raise ValueError("CSV witness must observe exactly the reviewed two changed source files")
    changed = {row.path: row for row in witness.changes}
    module, test = changed[MODULE], changed[TEST]
    if (module.before_sha256, module.after_sha256, test.before_sha256, test.after_sha256) != (
        pins.baseline_module_sha256,
        pins.post_module_sha256,
        pins.baseline_test_sha256,
        pins.post_test_sha256,
    ):
        raise ValueError("Actual observed CSV before/post digests differ from reviewed pins")
    return CsvObservedSources.model_validate(
        {
            "baseline_module_sha256": module.before_sha256,
            "post_module_sha256": module.after_sha256,
            "baseline_test_sha256": test.before_sha256,
            "post_test_sha256": test.after_sha256,
        }
    )


def _receipt_binding(
    value: EngineeringCheckInput, result: BuilderRunResult, role: Literal["author", "verifier"]
) -> None:
    receipt = value.author_receipt if role == "author" else value.verifier_receipt
    output = value.author_output if role == "author" else value.verifier_output
    job = result.spec.job
    if (
        (
            receipt.company_id,
            receipt.action_id,
            receipt.task_id,
            receipt.trace_id,
            receipt.proposal_hash,
            receipt.outcome,
        )
        != (
            job.company_id,
            job.action_id,
            job.task_id,
            job.trace_id,
            result.proposal_sha256,
            "succeeded",
        )
        or len(receipt.artifacts) != 1
        or (
            receipt.artifacts[0].artifact_id,
            receipt.artifacts[0].revision,
            receipt.artifacts[0].sha256,
        )
        != (output.artifact_id, output.revision, output.sha256)
    ):
        raise ValueError("CSV receipt/result/protected output binding differs")
