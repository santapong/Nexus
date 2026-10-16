"""Synthetic server configuration for composition tests; no live eligibility or company setup."""

from decimal import Decimal
from pathlib import Path

from nexus.company.brain.context import ContextSelection
from nexus.company.brain.retrieval import SearchRequest
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.management.planning_authority import PlanningRolePolicy
from nexus.execution.planning_application_config import PlanningApplicationConfig, PlanningStorage
from nexus.harness.model_authorizer_contracts import ModelInputRecipe
from nexus.harness.model_input_estimator import (
    RECIPE_ID,
    RECIPE_REVISION,
    input_conformance_reference,
)
from nexus.tests.unit.nexus_cycle_fixture import case, key


def configuration(root: Path) -> PlanningApplicationConfig:
    """Use existing closed role descriptions, never manufactured native registration."""
    admission, catalog = case()
    return PlanningApplicationConfig(
        catalog=catalog,
        policy_version="fixture-planning-policy",
        role_policy=PlanningRolePolicy(
            company_id=admission.company_id,
            workflow_name="company.planning.v1",
            workflow_version="v1",
            model_profile="reasoning",
            data_classification="internal",
            role_system_text="Plan bounded work from current cited Nexus evidence.",
        ),
        recipe=ModelInputRecipe(
            recipe_id=RECIPE_ID,
            revision=RECIPE_REVISION,
            profile="reasoning",
            minimum_score=Decimal("0.8"),
            evaluation_suite_version="synthetic-nexus-component",
            conformance_reference=input_conformance_reference(),
        ),
        selection=ContextSelection(
            company_id=admission.company_id,
            search=SearchRequest(company_id=admission.company_id, query="Nexus"),
        ),
        registry_id="nexus-planner",
        max_output_tokens=512,
        worker_id=key("application-worker"),
        mapping_revision="fixture-mapping-v1",
        source_policies=(
            SourcePolicy(
                source_symbol="fixture.nexus-docs.v1",
                authority_profile="fixture.committed-docs.v1",
                data_classification="internal",
                media_type="text/markdown",
                parser_version="utf8-identity-v1",
                chunker_version="utf8-sections-v1",
                search_config="simple",
                freshness_seconds=None,
                allowed_external_keys=frozenset({"ARCHITECTURE.md"}),
            ),
        ),
        storage=PlanningStorage(
            brain_root=root / "brain",
            prepared_root=root / "prepared",
            model_evidence_root=root / "model-evidence",
            brain_storage_symbol="fixture.planning.brain.v1",
            prepared_storage_symbol="fixture.planning.prepared.v1",
        ),
    )
