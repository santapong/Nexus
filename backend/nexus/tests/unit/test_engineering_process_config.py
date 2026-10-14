"""Closed process packet fields reject corrupt identities and paths before database preparation."""

from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.tests.builder_support import synthetic_capabilities
from nexus.tests.engineering_check_support import check_input
from nexus.tests.engineering_process_config import EngineeringProcessConfig
from nexus.tests.engineering_process_scope import PROCESS_ROOTS, require_process_root
from nexus.tests.integration.management_acceptance_source_fixture import Policies


def packet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    # Keep the >50-line descriptive typed fixture together so every corruption
    # starts from the same valid command, action, policy and exact source mapping.
    value = check_input()
    binding = value.target.verifier
    job = value.verifier.spec.job
    database = "nexus_company_test_engineering_process_intent"
    # Only pure fixture filesystem location changes; production packet map stays exact.
    monkeypatch.setitem(PROCESS_ROOTS, database, tmp_path)
    tmp_path.chmod(0o700)
    (tmp_path / "harmless-engineering-repository").mkdir(mode=0o700)
    command = SegmentCommand(
        company_id=job.company_id,
        task_id=job.task_id,
        trace_id=job.trace_id,
        actor_id=job.actor_id,
        workspace_id=job.workspace_id,
        run_id=job.run_id,
        action_id=job.action_id,
        segment_id=uuid4(),
    )
    output = value.verifier_output
    spec = value.verifier.spec
    # Construct explicit matching output pin for these purely descriptive fixtures.
    from nexus.company.brain.access_contracts import ResourceRef

    target = ResourceRef(company_id=job.company_id, resource_id=UUID(int=333))
    spec = spec.model_copy(update={"output_resource": target})
    action = ActionProposal(
        company_id=job.company_id,
        task_id=job.task_id,
        trace_id=job.trace_id,
        actor_id=job.actor_id,
        action_id=job.action_id,
        revision=1,
        tool="company.builder.run.v1",
        tool_version="v1",
        resource=job.resource_symbol,
        parameters=spec.model_dump(mode="json"),
        policy_version="fixture",
        price_version="fixture",
        estimated_cost_usd=Decimal("0.01"),
    )
    policies = Policies().policy("fixture.source.v1")
    rows = tuple(
        policies.model_copy(update={"source_symbol": symbol})
        for symbol in ["fixture.source.v1", "acceptance.fixture.9900", "acceptance.fixture.9500"]
    )
    capabilities = synthetic_capabilities().model_copy(
        update={"qualified_image": value.declaration.policy.image}
    )
    return {
        "catalog": PlanAdmissionCatalog(
            company_id=job.company_id,
            models=ModelRegistry(
                company_id=job.company_id,
                revision="fixture",
                pricebook_version="fixture",
                models=(),
            ),
            admitted_profiles=frozenset(),
            check_recipes=frozenset(),
        ),
        "declaration": value.declaration,
        "policy": value.declaration.policy,
        "capabilities": capabilities,
        "image_id": value.declaration.image_id,
        "database": database,
        "task_root": tmp_path,
        "source_root": tmp_path / "harmless-engineering-repository",
        "source_metadata": output,
        "output_target": target,
        "proof_target": target,
        "policies": rows,
        "verifier_binding": binding,
        "verifier_action": action,
        "verifier_spec": spec,
        "workflow_id": UUID(command.workflow_id),
        "command": command,
    }


@pytest.mark.parametrize(
    "field",
    ["company_id", "task_id", "trace_id", "actor_id", "workspace_id", "run_id", "action_id"],
)
def test_corrupt_command_identity_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    values = packet(tmp_path, monkeypatch)
    command = values["command"]
    assert isinstance(command, SegmentCommand)
    with pytest.raises(ValueError):
        EngineeringProcessConfig.model_validate(
            {**values, "command": command.model_copy(update={field: uuid4()})}
        )


@pytest.mark.parametrize(
    "field", ["workflow_id", "source_root", "task_root", "database", "image_id", "policies"]
)
def test_corrupt_packet_pin_or_path_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    values = packet(tmp_path, monkeypatch)
    changes = {
        "workflow_id": uuid4(),
        "source_root": Path("/home/santapong"),
        "task_root": Path("/tmp/arbitrary"),
        "database": "foreign",
        "image_id": "bad",
        "policies": (),
    }
    with pytest.raises(ValueError):
        EngineeringProcessConfig.model_validate({**values, field: changes[field]})


def test_exact_fixture_shape_and_closed_root_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = packet(tmp_path, monkeypatch)
    assert EngineeringProcessConfig.model_validate(values).command == values["command"]
    with pytest.raises(ValueError):
        require_process_root("foreign", tmp_path, existing=True)
    with pytest.raises(ValueError):
        require_process_root(
            "nexus_company_test_engineering_process_intent", Path("/tmp/arbitrary"), existing=False
        )


@pytest.mark.parametrize(
    "change", ["duplicate_policy", "foreign_spec", "action_parameters", "symlink", "public_root"]
)
def test_closed_policy_and_actual_ordinary_source_constraints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    values = packet(tmp_path, monkeypatch)
    if change == "duplicate_policy":
        rows = values["policies"]
        assert isinstance(rows, tuple)
        values["policies"] = (rows[0], rows[0], rows[2])
    elif change == "foreign_spec":
        from nexus.builder.execution_contracts import BuilderExecutionSpec

        spec = values["verifier_spec"]
        assert isinstance(spec, BuilderExecutionSpec)
        values["verifier_spec"] = spec.model_copy(
            update={"job": spec.job.model_copy(update={"run_id": uuid4()})}
        )
    elif change == "action_parameters":
        action = values["verifier_action"]
        assert isinstance(action, ActionProposal)
        values["verifier_action"] = action.model_copy(update={"parameters": {}})
    elif change == "symlink":
        original = tmp_path / "harmless-engineering-repository"
        original.rmdir()
        original.symlink_to(tmp_path, target_is_directory=True)
    else:
        tmp_path.chmod(0o755)
    with pytest.raises(ValueError):
        EngineeringProcessConfig.model_validate(values)
