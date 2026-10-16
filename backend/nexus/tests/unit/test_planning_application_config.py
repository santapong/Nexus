"""Server configuration pins descriptions; no live eligibility, native state or activation."""

import hashlib
from pathlib import Path

import pytest

from nexus.company.brain.context import ContextSelection
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.management.planning_authority import PlanningRolePolicy
from nexus.execution.planning_application_config import (
    PlanningApplicationConfig,
    PlanningStorage,
    parse_planning_config,
)
from nexus.harness.model_authorizer_contracts import ModelInputRecipe
from nexus.tests.unit.nexus_cycle_fixture import case


def configured(root: Path) -> PlanningApplicationConfig:
    admission, catalog = case()
    return PlanningApplicationConfig(
        catalog=catalog,
        policy_version="nexus.supervised.v1",
        role_policy=PlanningRolePolicy(
            company_id=admission.company_id,
            workflow_name="company.planning.v1",
            workflow_version="v1",
            model_profile="reasoning",
            data_classification="internal",
            role_system_text="Plan a cited Nexus change; never claim execution.",
        ),
        recipe=ModelInputRecipe(
            recipe_id="nexus.whole-request",
            revision="v1",
            profile="reasoning",
            minimum_score="0.8",
            evaluation_suite_version="synthetic-not-live-quality",
            conformance_reference="fixture:not-live-sdk-conformance",
        ),
        selection=ContextSelection(company_id=admission.company_id),
        registry_id=catalog.models.models[0].registry_id,
        max_output_tokens=512,
        worker_id=admission.slots[0].child.binding.actor_id,
        mapping_revision="nexus.goal-map.v1",
        source_policies=(
            SourcePolicy(
                source_symbol="nexus.docs",
                authority_profile="nexus.docs.v1",
                data_classification="internal",
                media_type="text/markdown",
                parser_version="utf8-identity-v1",
                chunker_version="utf8-sections-v1",
                search_config="simple",
                freshness_seconds=3600,
                allowed_external_keys=frozenset({"docs/company-system/ARCHITECTURE.md"}),
            ),
        ),
        storage=PlanningStorage(
            brain_root=root / "brain",
            prepared_root=root / "prepared",
            model_evidence_root=root / "models",
            brain_storage_symbol="nexus.docs.v1",
            prepared_storage_symbol="nexus.prepared.v1",
        ),
    )


def test_exact_pinned_config_roundtrips_without_native_activation(tmp_path: Path) -> None:
    value = configured(tmp_path)
    raw = value.model_dump_json(by_alias=True).encode()
    assert parse_planning_config(raw, hashlib.sha256(raw).hexdigest()) == value
    assert value.admission == value.catalog.nexus_cycle_admission
    assert value.goal == value.admission.goal


@pytest.mark.parametrize(
    "fault", ["hash", "extra", "duplicate", "overflow", "preview", "root", "recipe"]
)
def test_configuration_cannot_relabel_or_expand_fixed_server_choices(
    tmp_path: Path, fault: str
) -> None:
    raw = configured(tmp_path).model_dump_json().encode()
    if fault == "hash":
        with pytest.raises(ValueError):
            parse_planning_config(raw, "f" * 64)
        return
    if fault == "extra":
        raw = raw[:-1] + b',"api_key":"forbidden"}'
    elif fault == "duplicate":
        raw = b'{"policy_version":"other",' + raw[1:]
    elif fault == "overflow":
        raw = b" " * 262145
    elif fault == "preview":
        raw = raw.replace(b"nexus.supervised.v1", b"nexus-preview-no-provider-v1")
    elif fault == "root":
        raw = raw.replace(b'"allocation_usd":"1"', b'"allocation_usd":"0"', 1)
    elif fault == "recipe":
        raw = raw.replace(b'"profile":"reasoning"', b'"profile":"routine"', 1)
    with pytest.raises(ValueError):
        parse_planning_config(raw, hashlib.sha256(raw).hexdigest())
