"""Pure checker boundaries; pass cannot publish acceptance or prove model/engine execution."""

from pathlib import Path

import pytest

from nexus.builder.contracts import BuilderCommandReceipt
from nexus.builder.engineering_checker import check_engineering_change
from nexus.builder.result_codec import captured
from nexus.tests.engineering_check_support import check_input


def test_seven_exact_mechanical_checks_remain_descriptive_only() -> None:
    result = check_engineering_change(check_input())
    assert result.verdict == "pass" and len(result.criteria) == 7
    assert "business_readiness_unproven" in result.limitations


@pytest.mark.parametrize(
    "case", ["patch", "receipt", "goal", "model_quota", "image", "caps", "recipe"]
)
def test_spliced_or_unsupported_basis_cannot_pass(case: str) -> None:
    value = check_input()
    if case == "patch":
        value = value.model_copy(
            update={
                "author": value.author.model_copy(
                    update={
                        "spec": value.author.spec.model_copy(
                            update={
                                "protected_patch": None,
                                "job": value.author.spec.job.model_copy(
                                    update={"patch_sha256": None}
                                ),
                            }
                        )
                    }
                )
            }
        )
    if case == "receipt":
        value = value.model_copy(
            update={
                "verifier_receipt": value.verifier_receipt.model_copy(
                    update={"proposal_hash": "a" * 64}
                )
            }
        )
    if case == "goal":
        from uuid import uuid4

        value = value.model_copy(
            update={"declaration": value.declaration.model_copy(update={"goal_id": uuid4()})}
        )
    if case == "model_quota":
        registration = value.verifier_registration.model_copy(
            update={
                "quota": value.verifier_registration.quota.model_copy(update={"model_requests": 1})
            }
        )
        value = value.model_copy(update={"verifier_registration": registration})
    if case == "image":
        value = value.model_copy(
            update={"verifier": value.verifier.model_copy(update={"image_id": "a" * 64})}
        )
    if case == "caps":
        value = value.model_copy(
            update={
                "verifier": value.verifier.model_copy(update={"observed_memory_max": 4294967297})
            }
        )
    if case == "recipe":
        value = value.model_copy(
            update={
                "target": value.target.model_copy(
                    update={"check_recipe": "internal-report-mechanical-v1"}
                )
            }
        )
    assert check_engineering_change(value).verdict == "reject"


def test_actual_baseline_failure_cannot_become_post_approval() -> None:
    value = check_input()
    first = value.author.commands[0]
    failed = BuilderCommandReceipt(
        command_key=first.command_key,
        phase="baseline",
        outcome="exited",
        exit_code=7,
        elapsed_millis=1,
    )
    value = value.model_copy(
        update={
            "author": value.author.model_copy(
                update={"outcome": "commands_failed", "commands": (failed,)}
            )
        }
    )
    assert check_engineering_change(value).verdict == "reject"


@pytest.mark.parametrize("case", ["unknown", "skip", "missing_behavior", "kernel_unknown"])
def test_uncertainty_or_unexecuted_assertions_stay_inconclusive(case: str) -> None:
    value = check_input()
    result = value.verifier
    if case == "unknown":
        result = result.model_copy(
            update={"outcome": "outcome_unknown", "commands": (), "artifacts": ()}
        )
    if case == "skip":
        evidence = captured(
            "post/checks/behavior.json",
            b'{"schema_version":"nexus.engineering.behavior.v1","cases":[{"case_id":"fixture.quantity.v1","status":"skip"}]}',
        )
        result = result.model_copy(update={"artifacts": (result.artifacts[0], evidence)})
    if case == "missing_behavior":
        result = result.model_copy(update={"artifacts": (result.artifacts[0],)})
    if case == "kernel_unknown":
        result = result.model_copy(update={"observed_memory_max": None})
    value = value.model_copy(update={"verifier": result})
    assert check_engineering_change(value).verdict == "inconclusive"


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":"nexus.engineering.behavior.v1","schema_version":"nexus.engineering.behavior.v1","cases":[{"case_id":"fixture.quantity.v1","status":"pass"}]}',
        b'{"schema_version":"nexus.engineering.behavior.v1","cases":[{"case_id":"fixture.quantity.v1","status":"pass","status":"fail"}]}',
        b'{"schema_version":"nexus.engineering.behavior.v1","cases":[{"case_id":"fixture.quantity.v1","status":"pass"}],"unsupported":true}',
        b"\xff",
        b" " * 16385,
    ],
)
def test_duplicate_unknown_or_oversized_behavior_cannot_pass(raw: bytes) -> None:
    value = check_input()
    artifacts = (value.verifier.artifacts[0], captured("post/checks/behavior.json", raw))
    value = value.model_copy(
        update={"verifier": value.verifier.model_copy(update={"artifacts": artifacts})}
    )
    assert check_engineering_change(value).verdict == "inconclusive"


@pytest.mark.parametrize("case", ["foreign_path", "inventory", "source", "spec"])
def test_spliced_actual_inventory_witness_cannot_pass(case: str) -> None:
    from uuid import uuid4

    value = check_input()
    witness = value.verifier_witness
    if case == "foreign_path":
        changes = tuple(
            row.model_copy(update={"path": "forbidden/value.ts"}) for row in witness.changes
        )
        witness = witness.model_copy(update={"changes": changes})
    if case == "inventory":
        witness = witness.model_copy(update={"post_inventory_sha256": "a" * 64})
    if case == "source":
        witness = witness.model_copy(
            update={"source": witness.source.model_copy(update={"commit": uuid4().hex + "a" * 8})}
        )
    if case == "spec":
        witness = witness.model_copy(update={"spec_sha256": "a" * 64})
    value = value.model_copy(update={"verifier_witness": witness})
    assert check_engineering_change(value).verdict == "reject"


@pytest.mark.parametrize("case", ["oversized", "symlink", "hardlink", "wrong_spec"])
def test_witness_load_refuses_nonordinary_oversized_or_other_job_bytes(
    tmp_path: Path, case: str
) -> None:
    from nexus.builder.engineering_witness import WITNESS_PATH, load_witness

    value = check_input()
    path = tmp_path / WITNESS_PATH
    if case == "oversized":
        path.write_bytes(b" " * 16385)
    else:
        ordinary = tmp_path / "actual.json"
        witness = value.author_witness
        if case == "wrong_spec":
            witness = witness.model_copy(update={"spec_sha256": "a" * 64})
        ordinary.write_text(witness.model_dump_json())
        if case == "symlink":
            path.symlink_to(ordinary)
        elif case == "hardlink":
            path.hardlink_to(ordinary)
        else:
            ordinary.rename(path)
    with pytest.raises((ValueError, OSError)):
        load_witness(tmp_path, value.author.spec)


def test_witness_captures_actual_allowed_change_and_refuses_unchanged_source(
    tmp_path: Path,
) -> None:
    from nexus.builder.engineering_witness import capture_witness, load_witness

    value = check_input()
    for phase in ("baseline", "post"):
        target = tmp_path / phase / "apps/web/src"
        target.mkdir(parents=True, mode=0o700)
        (tmp_path / phase).chmod(0o700)
        (target / "value.ts").write_text("before")
    with pytest.raises(ValueError):
        capture_witness(tmp_path, value.author.spec)
    (tmp_path / "post/apps/web/src/value.ts").write_text("after")
    witness = capture_witness(tmp_path, value.author.spec)
    assert witness.changes[0].path == "apps/web/src/value.ts"
    assert witness.changes[0].before_sha256 != witness.changes[0].after_sha256
    assert load_witness(tmp_path, value.author.spec) == witness
