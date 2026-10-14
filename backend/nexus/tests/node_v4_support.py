"""Synthetic pure check descriptions plus actual public fixture reports; no operative authority."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from nexus.builder.csv_behavior_wrapper import CASES
from nexus.builder.csv_report_contracts import CsvRegressionPins
from nexus.builder.engineering_contracts import EngineeringChangedFile, EngineeringCheckInput
from nexus.builder.execution_contracts import CapturedFile
from nexus.builder.node_contracts import NodeRuntimeInputs
from nexus.builder.node_recipe import command_policies, command_references
from nexus.builder.node_v4_recipe import v4_recipe_sha256
from nexus.builder.result_codec import captured
from nexus.company.management.canonical import canonical_sha256
from nexus.tests.engineering_check_support import check_input

ROOT = Path(__file__).parent / "fixtures/csv-vitest-2.1.9"


def csv_pins() -> CsvRegressionPins:
    """Use genuine synthetic wrapper/report source pins, never live StockFlow pins."""
    return CsvRegressionPins.model_validate_json((ROOT / "pins.json").read_bytes())


def v4_inputs() -> NodeRuntimeInputs:
    return NodeRuntimeInputs(
        recipe="nexus.builder.node.v4",
        tool_symbol="fixture.tool",
        cache_symbol="fixture.cache",
        image_id="1" * 64,
        node_version="22.23.3",
        pnpm_version="9.12.0",
        pnpm_archive_sha256="2" * 64,
        pnpm_integrity="sha512-" + "A" * 86 + "==",
        cache_archive_sha256="3" * 64,
        cache_manifest_sha256="4" * 64,
        lock_sha256="5" * 64,
        command_recipe_sha256=v4_recipe_sha256(),
        csv_regression=csv_pins(),
    )


def described_v4_check() -> EngineeringCheckInput:
    """Pure constructed receipt bindings use actual synthetic JSON; no native publication proof."""
    value, pins = check_input(), v4_inputs()
    assert pins.csv_regression is not None
    policy = value.declaration.policy.model_copy(
        update={
            "runtime_inputs": pins,
            "commands": command_policies(),
            "write_paths": (
                "packages/shared/src/csv/index.ts",
                "packages/shared/src/csv/csv.test.ts",
            ),
        }
    )
    results, witnesses = [], []
    for result, witness in (
        (value.author, value.author_witness),
        (value.verifier, value.verifier_witness),
    ):
        spec = result.spec.model_copy(
            update={
                "runtime_inputs": pins,
                "policy_sha256": canonical_sha256(policy),
                "job": result.spec.job.model_copy(
                    update={"commands": command_references(), "write_paths": policy.write_paths}
                ),
            }
        )
        artifacts = tuple(
            captured(name, (ROOT / file).read_bytes())
            for name, file in (
                ("baseline/checks/shared-vitest.json", "baseline-checks-shared-vitest.json"),
                ("baseline/checks/web-vitest.json", "baseline-checks-web-vitest.json"),
                ("post/checks/csv-before-vitest.json", "post-checks-csv-before-vitest.json"),
                ("post/checks/shared-vitest.json", "post-checks-shared-vitest.json"),
                ("post/checks/web-vitest.json", "post-checks-web-vitest.json"),
            )
        )
        # Explicitly constructed canonical observation descriptions, not a native execution receipt.
        artifacts = (*artifacts, *_canonical_observations(artifacts, pins.csv_regression))
        result = result.model_copy(
            update={
                "spec": spec,
                "commands": tuple(
                    result.commands[0].model_copy(
                        update={"phase": row.phase, "command_key": row.command_key}
                    )
                    for row in spec.job.commands
                ),
                "artifacts": artifacts,
            }
        )
        changes = tuple(
            EngineeringChangedFile(path=path, before_sha256=before, after_sha256=after)
            for path, before, after in sorted(
                (
                    (
                        "packages/shared/src/csv/index.ts",
                        pins.csv_regression.baseline_module_sha256,
                        pins.csv_regression.post_module_sha256,
                    ),
                    (
                        "packages/shared/src/csv/csv.test.ts",
                        pins.csv_regression.baseline_test_sha256,
                        pins.csv_regression.post_test_sha256,
                    ),
                )
            )
        )
        witnesses.append(
            witness.model_copy(update={"spec_sha256": canonical_sha256(spec), "changes": changes})
        )
        results.append(result)
    return value.model_copy(
        update={
            "author": results[0],
            "verifier": results[1],
            "author_witness": witnesses[0],
            "verifier_witness": witnesses[1],
            "declaration": value.declaration.model_copy(
                update={
                    "policy": policy,
                    "csv_regression": pins.csv_regression,
                    "behavior_case_ids": tuple(row[0] for row in CASES),
                }
            ),
        }
    )


def _canonical_observations(
    artifacts: tuple[CapturedFile, ...], pins: CsvRegressionPins
) -> tuple[CapturedFile, ...]:
    outputs = []
    for phase in ("baseline", "post"):
        observation = json.loads(
            (ROOT / f"{phase}-checks-csv-wrapper-observation.json").read_bytes()
        )
        observation["pins_sha256"] = hashlib.sha256(pins.model_dump_json().encode()).hexdigest()
        for row in artifacts:
            if row.metadata.path.startswith(phase + "/"):
                raw = base64.b64decode(row.content_base64)
                assert hashlib.sha256(raw).hexdigest() == row.metadata.sha256
        outputs.append(
            captured(
                f"{phase}/checks/csv-wrapper-observation.json",
                json.dumps(observation, separators=(",", ":")).encode(),
            )
        )
    return tuple(outputs)
