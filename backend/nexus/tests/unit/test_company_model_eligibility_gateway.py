"""Current observations never replace original registration bytes or old evidence codecs."""

import json
import sys
from datetime import timedelta
from pathlib import Path
from types import ModuleType

import pytest

from nexus.company.management.canonical import canonical_json, canonical_sha256
from nexus.core.llm.company_adapter_contracts import ServerEndpoint
from nexus.core.llm.company_adapters import CompanyModelAdapters
from nexus.core.llm.company_eligibility import eligibility_provenance, validated_observations
from nexus.core.llm.company_registry import ModelRegistry
from nexus.core.llm.company_routing import RoutingDeniedError, route_models
from nexus.harness.model_evidence import ModelEvidence
from nexus.tests.unit.test_company_model_observations import catalog, observed
from nexus.tests.unit.test_company_model_registry import NOW, policy
from nexus.tests.unit.test_company_provider_conformance import Authorizer


class NoEndpoint:
    async def resolve(self, endpoint_id: str) -> ServerEndpoint:
        raise AssertionError("Missing current gate must deny before endpoint lookup")


def test_default_model_evidence_registry_request_codecs_remain_exact() -> None:
    value = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "fixtures/company-model-evidence-before-observations.json"
        ).read_text()
    )
    evidence = ModelEvidence.model_validate_json(value["evidence_json"])
    evidence.require_binding()
    # Legacy frozenset JSON order depends on construction, so compare the exact
    # old/new serializers using identical immutable nested typed inputs.
    module = ModuleType("_frozen_model_evidence_before_observations")
    sys.modules[module.__name__] = module
    source = (
        Path(__file__).resolve().parents[1]
        / "fixtures/company-model-evidence-before-observations.py.txt"
    )
    exec(compile(source.read_text(), str(source), "exec"), module.__dict__)
    old_type = module.__dict__["ModelEvidence"]
    old = old_type.model_validate({name: getattr(evidence, name) for name in old_type.model_fields})
    assert evidence.model_dump_json(by_alias=True) == old.model_dump_json(by_alias=True)
    assert canonical_json(evidence) == value["evidence_canonical_json"]
    assert canonical_sha256(evidence) == value["evidence_sha256"]
    assert "eligibility_provenance" not in evidence.model_dump()
    assert evidence.request.model_dump_json(by_alias=True) == value["request_json"]
    registry = ModelRegistry.model_validate_json(value["registry_json"])
    assert canonical_sha256(registry) == value["registry_canonical_sha256"]


def test_current_provenance_pins_original_bytes_and_exact_observation() -> None:
    original = catalog().models
    before = original.model_dump_json()
    observations = validated_observations(original, (observed(),))
    result = eligibility_provenance(original, observations, original.models[0])
    assert result is not None
    assert result.registration_sha256 == canonical_sha256(original.models[0])
    assert result.observation == observed()
    assert result.observation_sha256 == canonical_sha256(observed())
    result.require_binding(original.models[0], original.company_id, original.revision)
    assert original.model_dump_json() == before
    assert eligibility_provenance(original, (), original.models[0]) is None


def test_observed_adapter_requires_actual_pre_sdk_gate_not_only_a_declared_claim() -> None:
    with pytest.raises(ValueError, match="trusted pre-SDK"):
        CompanyModelAdapters(
            catalog().models, NoEndpoint(), Authorizer(), model_observations=(observed(),)
        )


def test_routing_uses_current_observation_without_relabeling_original_registry() -> None:
    original = catalog().models
    before = original.model_dump()
    with pytest.raises(RoutingDeniedError):
        route_models(original, policy(max_fallbacks=0), now=NOW + timedelta(minutes=10))
    result = route_models(
        original,
        policy(max_fallbacks=0),
        now=NOW + timedelta(minutes=10),
        model_observations=(observed(),),
    )
    assert original.model_dump() == before
    assert result.registry_revision == original.revision
    assert result.primary.model.price == original.models[0].price
    assert result.primary.model.endpoint_id == original.models[0].endpoint_id
    assert result.primary.model.health == observed().health


@pytest.mark.parametrize(
    "case", ["unknown", "future", "stale", "evaluation", "price", "capability"]
)
def test_current_observation_cannot_bypass_other_model_constraints(case: str) -> None:
    original = catalog().models
    observation = observed()
    if case in {"unknown", "future", "stale"}:
        changes = (
            {"status": "unknown"}
            if case == "unknown"
            else {
                "checked_at": NOW + timedelta(minutes=11) if case == "future" else NOW,
                "expires_at": NOW + timedelta(minutes=20)
                if case == "future"
                else NOW + timedelta(minutes=9),
            }
        )
        observation = observation.model_copy(
            update={"health": observation.health.model_copy(update=changes)}
        )
    elif case == "evaluation":
        observation = observation.model_copy(update={"evaluations": ()})
    else:
        model = original.models[0].model_copy(
            update={"price": None} if case == "price" else {"capabilities": frozenset({"text"})}
        )
        original = original.model_copy(update={"models": (model,)})
        observation = observation.model_copy(
            update={"registration_sha256": canonical_sha256(model)}
        )
    with pytest.raises(ValueError):
        route_models(
            original,
            policy(max_fallbacks=0),
            now=NOW + timedelta(minutes=10),
            model_observations=(observation,),
        )


@pytest.mark.parametrize("tamper", ["registration", "duplicate", "observation"])
def test_wrong_or_conflicting_provenance_does_not_become_current_qualification(tamper: str) -> None:
    original = catalog().models
    observation = observed()
    if tamper == "registration":
        with pytest.raises(ValueError):
            validated_observations(
                original, (observation.model_copy(update={"registration_sha256": "0" * 64}),)
            )
    elif tamper == "duplicate":
        with pytest.raises(ValueError):
            validated_observations(original, (observation, observation))
    else:
        result = eligibility_provenance(original, (observation,), original.models[0])
        assert result is not None
        changed = result.model_copy(
            update={
                "observation": observation.model_copy(
                    update={
                        "health": observation.health.model_copy(
                            update={
                                "expires_at": observation.health.expires_at + timedelta(minutes=1)
                            }
                        )
                    }
                )
            }
        )
        with pytest.raises(ValueError):
            changed.require_binding(original.models[0], original.company_id, original.revision)
