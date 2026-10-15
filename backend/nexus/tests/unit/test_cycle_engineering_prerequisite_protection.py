"""Original temporal observations cannot be rescued by a renewed current window."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest

from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.cycle_artifacts.native_contracts import CycleEngineeringReadProtection
from nexus.company.management.acceptance_freshness import QualifiedFreshness
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.tests.unit.cycle_prerequisite_fixture import (
    NOW,
    deliverable_case,
    own_lease,
    signed_identity,
)


async def protection(monkeypatch: pytest.MonkeyPatch) -> CycleEngineeringReadProtection:
    case = deliverable_case(monkeypatch)
    policy = SourcePolicy(
        source_symbol="fixture.cycle",
        authority_profile="fixture.reader",
        data_classification="internal",
        origin_kind="derived",
        media_type="application/json",
        parser_version="v1",
        chunker_version="v1",
        search_config="simple",
        freshness_seconds=60,
    )
    freshness = QualifiedFreshness(UUID(int=123), policy, NOW + timedelta(seconds=20), True)
    catalog = PlanAdmissionCatalog(
        company_id=case.work.company_id,
        models=case.cycle.registry,
        admitted_profiles=frozenset(),
        check_recipes=frozenset(),
    )
    return CycleEngineeringReadProtection(
        NOW,
        (freshness,),
        (
            ResourceGeneration(
                company_id=case.work.company_id,
                resource_id=UUID(int=124),
                generation=1,
                expires_at=NOW + timedelta(seconds=15),
            ),
        ),
        await signed_identity(case.identity),
        own_lease(case),
        catalog,
        (),
        (),
        ("p1", "p1"),
        (),
        (),
    )


@pytest.mark.parametrize("kind", ["lease", "grant", "source", "credential"])
async def test_original_expiry_denies_even_when_current_is_renewed(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    first = await protection(monkeypatch)
    if kind == "lease":
        first = replace(
            first, lease=first.lease.model_copy(update={"expires_at": NOW + timedelta(seconds=1)})
        )
    elif kind == "grant":
        first = replace(
            first,
            grants=(first.grants[0].model_copy(update={"expires_at": NOW + timedelta(seconds=1)}),),
        )
    elif kind == "source":
        first = replace(
            first, freshness=(replace(first.freshness[0], fresh_until=NOW + timedelta(seconds=1)),)
        )
    else:
        # Genuine signed witness time is checked, with no mutable witness fabrication.
        with pytest.raises(ValueError):
            first.require_time(first.credential.expires_at)
        return
    current = replace(
        first,
        lease=first.lease.model_copy(update={"expires_at": NOW + timedelta(seconds=90)}),
        grants=(first.grants[0].model_copy(update={"expires_at": NOW + timedelta(seconds=90)}),),
        freshness=(replace(first.freshness[0], fresh_until=NOW + timedelta(seconds=90)),),
    )
    current.require_time(NOW + timedelta(seconds=2))
    with pytest.raises(ValueError):
        first.require_time(NOW + timedelta(seconds=2))


async def test_none_requires_an_actual_registered_no_ttl_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await protection(monkeypatch)
    unknown = replace(value.freshness[0], fresh_until=None)
    with pytest.raises(ValueError):
        replace(value, freshness=(unknown,)).require_time(NOW)
    no_ttl = unknown.policy.model_copy(update={"freshness_seconds": None})
    replace(value, freshness=(replace(unknown, policy=no_ttl),)).require_time(NOW)


async def test_only_initially_eligible_model_alternatives_can_survive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    from nexus.company.management.plan_admission_window import (
        PlanChildWindow,
        PlanModelCandidateWindow,
    )
    from nexus.core.llm.company_registry import EvaluationEvidence, ModelHealth

    case = deliverable_case(monkeypatch)
    candidate = PlanModelCandidateWindow(
        "fixture-model",
        "a" * 64,
        "b" * 64,
        ModelHealth(
            status="healthy",
            checked_at=NOW - timedelta(seconds=1),
            expires_at=NOW + timedelta(seconds=1),
        ),
        EvaluationEvidence(
            profile="routine",
            suite_version="v1",
            artifact_reference="fixture.eval",
            score=Decimal(1),
            conformance_passed=True,
            evaluated_at=NOW - timedelta(seconds=1),
            expires_at=NOW + timedelta(seconds=20),
        ),
    )
    slot = case.cycle.admission.slots[4].child
    original = PlanChildWindow(slot.binding, slot.quota, "ordinary", None, (candidate,))
    original.require_time(NOW)
    with pytest.raises(ValueError):
        original.require_time(NOW + timedelta(seconds=2))
