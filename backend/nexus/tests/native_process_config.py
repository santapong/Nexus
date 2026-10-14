"""Private subprocess fixture configuration contains data/registry pins, never execution permits."""

from pathlib import Path

from pydantic import Field

from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.management.base import ValueContract
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactRule
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.tests.generated_artifact_fixture import GeneratedScenario


class NativeProcessConfig(ValueContract):
    """Reconstruct actual configured services after a process death, not cached output authority."""

    catalog: PlanAdmissionCatalog
    policies: tuple[SourcePolicy, ...] = Field(min_length=1, max_length=32)
    rules: tuple[GeneratedArtifactRule, ...] = Field(min_length=1, max_length=2)


def save_process_config(root: Path, scenario: GeneratedScenario) -> None:
    """Persist the server registry actually used for this approved source/work fixture."""
    policies = scenario.producer.inputs.source_policies
    symbols = ("fixture.source.v1", *(row.source_policy for row in scenario.rules))
    value = NativeProcessConfig(
        catalog=scenario.plans.catalog,
        policies=tuple(policies.policy(key) for key in symbols),
        rules=scenario.rules,
    )
    (root / "native-process-config.json").write_text(value.model_dump_json())
