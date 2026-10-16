"""Deny-only exact C store/model composition; no serialized permission or fallback."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_prepared_checks import require_action_header
from nexus.company.management.coding_stored_intent import StoredCodingIntent
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.planning_native_facts import require_time
from nexus.execution.intent_checks import BeforeIntentCheck, CompositeBeforeIntentCheck
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.harness.model_authorizer_contracts import model_action_parameters
from nexus.harness.model_input_estimator import FullContextInputEstimator
from nexus.harness.model_intent import ModelIntentCheck

if TYPE_CHECKING:
    from nexus.execution.effect_store import EffectStore


def nexus_coding_stored_shape(
    factory: async_sessionmaker[AsyncSession],
    effects: EffectStore,
    catalog: PlanAdmissionCatalog,
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    proposal: ActionProposal,
    check: BeforeIntentCheck | None,
) -> tuple[object, ...]:
    """Require real worker issuance and capture original objects/values across native awaits.

    This cohesive >50-line comparison is deliberately adjacent: a marker, actor
    read, cloned proof, bare C check or otherwise valid model check cannot fill
    one missing part. Actual async Stored/Model/Stored checks remain mandatory.
    """
    if type(check) is not CompositeBeforeIntentCheck or len(check._checks) != 3:
        raise ValueError("Coding needs its exact original stored/model/stored composite")
    stored, model, repeated = check._checks
    if (
        type(stored) is not StoredCodingIntent
        or type(model) is not ModelIntentCheck
        or repeated is not stored
    ):
        raise ValueError("Coding needs its exact original stored/model/stored composite")
    stored.require_composition()
    store, loaded = stored.store, stored.stored
    store.require_loaded(loaded, stored.credential, lease)
    prepared, header = loaded.prepared, loaded.header
    actual = next(
        (row for row in model.registry.models if row.registry_id == model.call.registry_id), None
    )
    if (
        store.factory is not factory
        or stored.factory is not factory
        or store.management.catalog is not catalog
        or effects._factory is not factory
        or effects._management_catalog is not catalog
        or effects._management_artifacts is not store.management.artifacts
        or effects._management_freshness is not store.management.freshness
        or store.contexts is not stored._context_check._revalidator
        or stored._context_check._lease != lease
        or stored.credential.identity != identity
        or model.lease != lease
        or type(model.estimator) is not FullContextInputEstimator
        or model.call != prepared.request
        or model.recipe != prepared.input_recipe
        or model.recipe != store.recipe
        or model.registry != stored.registry
        or model.registry != catalog.models
        or model.classification != prepared.request.data_classification
        or model.observations != catalog.model_observations
        or actual is None
        or header.registry_sha256 != canonical_sha256(model.registry)
        or header.model_sha256 != canonical_sha256(actual)
        or prepared.input_estimate.whole_request is None
        or model.estimator.estimate(model.call, model.registry, model.recipe)
        != prepared.input_estimate
        or proposal.parameters != model_action_parameters(model.call, model.recipe)
        or proposal.estimated_cost_usd != model.quote.amount_usd
        or (proposal.price_version, model.quote.price_version, model.quote.basis)
        != (model.call.price_version, model.call.price_version, "upper_bound")
        or (model.call.registry_revision, model.call.price_version)
        != (model.registry.revision, model.registry.pricebook_version)
        or (model.original_model is not None and model.original_model != actual)
        or (model.estimate is not None and model.estimate != prepared.input_estimate)
    ):
        raise ValueError("Coding original store/model/source/financial composition differs")
    require_action_header(proposal, header)
    # Identity pins deny even equal-value replacements; immutable values detect
    # nested mutation on the original request/recipe/registry/observation objects.
    objects = (
        check,
        stored,
        model,
        stored.original,
        store,
        loaded,
        stored.credential,
        store.contexts,
        store.management,
        store.sources,
        store.sources.artifacts,
        store.sources.artifacts.blobs,
        store.sources.freshness,
        store.blobs,
        store.repository,
        store._io,
        store.contexts._authority,
        store.contexts._retriever,
        model.call,
        model.quote,
        model.recipe,
        model.registry,
        model.estimator,
        model.observations,
        model.lease,
    )
    result = (
        objects,
        tuple(id(value) for value in objects),
        stored.original.fingerprint(),
        store._fingerprint(loaded),
        model.call.model_dump_json(by_alias=True),
        model.quote.model_dump_json(),
        model.recipe.model_dump_json(),
        model.registry.model_dump_json(),
        model.classification,
        json.dumps([row.model_dump(mode="json") for row in model.observations], sort_keys=True),
        (
            model.estimator._registry_sha256,
            model.estimator._recipe_sha256,
            model.estimator._conformance,
        ),
        store.repository.selection_sha256,
    )
    # Full estimation/serialization above can cross the already-owned source
    # window. Deny at the original cutoff after all CPU, with no refreshed read.
    stored.require_composition()
    store.require_loaded(loaded, stored.credential, lease)
    require_time(loaded.read_end_us)
    return result
