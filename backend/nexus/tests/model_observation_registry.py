"""Synthetic fresh observation pins an actually unchanged expired fixture registration."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.model_observations import ModelEligibilityObservation
from nexus.core.llm.company_registry import ModelRegistry
from nexus.tests.integration.test_company_directory import COMPANY
from nexus.tests.integration.test_company_model_authorizer import current_registry


def observed_registry(
    expires_seconds: int = 3600,
) -> tuple[ModelRegistry, ModelEligibilityObservation]:
    now = datetime.now(UTC)
    source = current_registry()
    model = source.models[0]
    assert model.price is not None
    original = model.model_copy(
        update={
            "price": model.price.model_copy(
                update={
                    "version": "fixture-prices",
                    "as_of": now.date(),
                    "valid_from": now - timedelta(minutes=1),
                    "valid_until": now + timedelta(hours=1),
                }
            ),
            "health": model.health.model_copy(
                update={
                    "checked_at": now - timedelta(minutes=20),
                    "expires_at": now - timedelta(minutes=10),
                }
            ),
            "evaluations": tuple(
                value.model_copy(
                    update={
                        "evaluated_at": now - timedelta(minutes=20),
                        "expires_at": now - timedelta(minutes=10),
                    }
                )
                for value in model.evaluations
            ),
        }
    )
    registry = ModelRegistry.model_validate(
        source.model_dump()
        | {
            "revision": "fixture-registry-v1",
            "pricebook_version": "fixture-prices",
            "models": (original,),
        }
    )
    observation = ModelEligibilityObservation(
        company_id=COMPANY,
        observation_id=uuid4(),
        registry_id=original.registry_id,
        registry_revision=registry.revision,
        registration_sha256=canonical_sha256(original),
        receipt_sha256="8" * 64,
        health=original.health.model_copy(
            update={
                "checked_at": now - timedelta(minutes=1),
                "expires_at": now + timedelta(seconds=expires_seconds),
            }
        ),
        evaluations=tuple(
            value.model_copy(
                update={
                    "evaluated_at": now - timedelta(minutes=1),
                    "expires_at": now + timedelta(seconds=expires_seconds),
                }
            )
            for value in original.evaluations
        ),
    )
    return registry, observation
