"""Fresh explicit eligibility preserves immutable registrations and fails closed."""

from datetime import date, timedelta
from uuid import UUID

import pytest

from nexus.company.management.canonical import canonical_json, canonical_sha256
from nexus.company.management.governance import CharterRevision
from nexus.company.management.model_observations import (
    ModelEligibilityObservation,
    effective_model_registration,
)
from nexus.company.management.plan_support import (
    PlanAdmissionCatalog,
    validate_plan_action,
    validate_plan_profile,
)
from nexus.company.management.plans import ChildAllocation
from nexus.tests.management_control_support import charter
from nexus.tests.unit.test_company_foundation import proposal
from nexus.tests.unit.test_company_management_plans import payload
from nexus.tests.unit.test_company_model_registry import COMPANY, NOW, model, registry


def catalog() -> PlanAdmissionCatalog:
    """Explicit synthetic registration, no provider or current execution authority."""
    return PlanAdmissionCatalog(
        company_id=COMPANY,
        models=registry(model()),
        admitted_profiles=frozenset({"engineering"}),
        check_recipes=frozenset(),
    )


def observed() -> ModelEligibilityObservation:
    """Synthetic current observation pins every byte of the original registration."""
    original = catalog().models.models[0]
    return ModelEligibilityObservation(
        company_id=COMPANY,
        observation_id=UUID(int=803),
        registry_revision="registry-1",
        registry_id=original.registry_id,
        registration_sha256=canonical_sha256(original),
        receipt_sha256="8" * 64,
        health=original.health.model_copy(
            update={
                "checked_at": NOW + timedelta(minutes=9),
                "expires_at": NOW + timedelta(minutes=20),
            }
        ),
        evaluations=original.evaluations,
    )


def child() -> ChildAllocation:
    """Use real child DTO with this fixture's exact immutable registry binding."""
    current = payload().children[0]
    return current.model_copy(
        update={
            "binding": current.binding.model_copy(
                update={
                    "model_registry_version": "registry-1",
                    "model_profile": "engineering",
                }
            )
        }
    )


def test_default_observations_preserve_exact_catalog_encoding() -> None:
    original = catalog()
    assert "model_observations" not in original.model_dump()
    assert "model_observations" not in original.model_dump_json()
    assert canonical_sha256(original) == canonical_sha256(
        PlanAdmissionCatalog.model_validate_json(original.model_dump_json())
    )
    assert '"as_of":"2026-10-13"' in canonical_json(original)
    assert original.models.models[0].price is not None
    assert original.models.models[0].price.as_of == date(2026, 10, 13)
    before = PlanAdmissionCatalog(
        company_id=COMPANY,
        models=registry(model(price=None)),
        admitted_profiles=frozenset({"engineering"}),
        check_recipes=frozenset(),
    )
    # Golden from unchanged pre-observation snapshot a5548bd, checked 2026-10-14.
    assert (
        canonical_sha256(before)
        == "340636ac7b9f73b742078b5fe8762730f31728357e98ead40c6865e09178cca8"
    )


def test_fresh_explicit_observation_preserves_original_registration_and_binding() -> None:
    original = catalog()
    with pytest.raises(ValueError, match="current registered"):
        validate_plan_profile(original, child(), NOW + timedelta(minutes=10))
    updated = PlanAdmissionCatalog.model_validate(
        original.model_dump() | {"model_observations": (observed(),)}
    )
    validate_plan_profile(updated, child(), NOW + timedelta(minutes=10))
    assert updated.models == original.models
    # Registry identity uses canonical bytes; frozenset JSON iteration order is unspecified.
    assert canonical_json(updated.models) == canonical_json(original.models)
    assert updated.models.revision == child().binding.model_registry_version


@pytest.mark.parametrize("splice", ["company", "revision", "hash", "unknown", "duplicate"])
def test_observation_cannot_replace_another_registration(splice: str) -> None:
    changes_by_splice: dict[str, dict[str, object]] = {
        "company": {"company_id": UUID(int=900)},
        "revision": {"registry_revision": "registry-2"},
        "hash": {"registration_sha256": "0" * 64},
        "unknown": {"registry_id": "missing"},
        "duplicate": {},
    }
    record = observed().model_copy(update=changes_by_splice[splice])
    observations = (record, record) if splice == "duplicate" else (record,)
    with pytest.raises(ValueError):
        PlanAdmissionCatalog.model_validate(
            catalog().model_dump() | {"model_observations": observations}
        )


@pytest.mark.parametrize("failure", ["expired", "future", "unhealthy", "failed"])
def test_current_negative_observation_never_falls_back_to_original_positive(failure: str) -> None:
    original = catalog()
    record = observed()
    health = record.health.model_copy(
        update={"checked_at": NOW - timedelta(minutes=1), "expires_at": NOW + timedelta(minutes=2)}
    )
    evaluations = record.evaluations
    if failure == "expired":
        health = health.model_copy(update={"expires_at": NOW})
    elif failure == "future":
        health = health.model_copy(update={"checked_at": NOW + timedelta(minutes=1)})
    elif failure == "unhealthy":
        health = health.model_copy(update={"status": "unhealthy"})
    else:
        evaluations = tuple(
            row.model_copy(update={"conformance_passed": False}) for row in evaluations
        )
    record = record.model_copy(update={"health": health, "evaluations": evaluations})
    updated = PlanAdmissionCatalog.model_validate(
        original.model_dump() | {"model_observations": (record,)}
    )
    validate_plan_profile(original, child(), NOW)
    with pytest.raises(ValueError, match="current registered"):
        validate_plan_profile(updated, child(), NOW)


@pytest.mark.parametrize("field", ["enabled", "endpoint_id", "allowed_data", "price"])
def test_observation_cannot_change_immutable_effect_fields(field: str) -> None:
    original = catalog()
    source = original.models.models[0]
    assert source.price is not None
    replacements = {
        "enabled": False,
        "endpoint_id": "changed-endpoint",
        "allowed_data": frozenset({"public"}),
        "price": source.price.model_copy(update={"source_reference": "changed-price"}),
    }
    changed = source.model_copy(update={field: replacements[field]})
    with pytest.raises(ValueError, match="changed registration"):
        effective_model_registration(original.models, (observed(),), changed)


def test_missing_observation_does_not_extend_old_expiry_or_create_model() -> None:
    original = catalog()
    source = original.models.models[0]
    assert effective_model_registration(original.models, (), source) is source
    with pytest.raises(ValueError, match="current registered"):
        validate_plan_profile(original, child(), NOW + timedelta(minutes=10))


def test_direct_helper_rejects_complete_conflicting_observation_tuple() -> None:
    original = catalog()
    first = observed()
    second = first.model_copy(
        update={
            "observation_id": UUID(int=804),
            "health": first.health.model_copy(update={"status": "unhealthy"}),
        }
    )
    with pytest.raises(ValueError, match="unique exact model"):
        effective_model_registration(original.models, (first, second), original.models.models[0])


def test_selected_model_action_preserves_other_current_observations_without_splicing() -> None:
    original = catalog()
    second = model("fixture-b", endpoint_id="second-endpoint")
    models = registry(original.models.models[0], second)
    observation = observed().model_copy(
        update={
            "observation_id": UUID(int=805),
            "registry_id": second.registry_id,
            "registration_sha256": canonical_sha256(second),
        }
    )
    current = PlanAdmissionCatalog.model_validate(
        original.model_dump()
        | {
            "models": models,
            "model_observations": (observed(), observation),
        }
    )
    declaration = charter()
    selected_charter = CharterRevision(
        company_id=COMPANY,
        department_id=declaration.department_id,
        revision_id=UUID(int=806),
        version=declaration.version,
        sha256=canonical_sha256(declaration),
        charter=declaration,
        mandate=payload().mandate,
        recorded_by=UUID(int=3),
        recorded_at=NOW,
    )
    action = proposal().model_copy(
        update={
            "tool": "model.request.v1",
            "tool_version": "v1",
            "resource": "model:fixture-a",
        }
    )
    validate_plan_action(
        current, child(), selected_charter, action, "model_requests", NOW + timedelta(minutes=10)
    )
    with pytest.raises(ValueError, match="unregistered model"):
        validate_plan_action(
            current,
            child(),
            selected_charter,
            action.model_copy(
                update={
                    "resource": "model:missing",
                }
            ),
            "model_requests",
            NOW + timedelta(minutes=10),
        )
