"""Original temporal observations cannot be rescued by a renewed current window."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.cycle_artifacts.native_contracts import CycleEngineeringReadProtection
from nexus.company.management.acceptance_freshness import QualifiedFreshness
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.tests.unit.cycle_prerequisite_fixture import (
    deliverable_case,
    own_lease,
    signed_identity,
)


async def protection(monkeypatch: pytest.MonkeyPatch) -> CycleEngineeringReadProtection:
    now = datetime.now(UTC)
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
    freshness = QualifiedFreshness(UUID(int=123), policy, now + timedelta(seconds=20), True)
    catalog = PlanAdmissionCatalog(
        company_id=case.work.company_id,
        models=case.cycle.registry,
        admitted_profiles=frozenset(),
        check_recipes=frozenset(),
    )
    return CycleEngineeringReadProtection(
        now,
        (freshness,),
        (
            ResourceGeneration(
                company_id=case.work.company_id,
                resource_id=UUID(int=124),
                generation=1,
                expires_at=now + timedelta(seconds=15),
            ),
        ),
        await signed_identity(case.identity, now=now),
        own_lease(case, now=now),
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
    now = first.observed_at
    if kind == "lease":
        first = replace(
            first, lease=first.lease.model_copy(update={"expires_at": now + timedelta(seconds=1)})
        )
    elif kind == "grant":
        first = replace(
            first,
            grants=(first.grants[0].model_copy(update={"expires_at": now + timedelta(seconds=1)}),),
        )
    elif kind == "source":
        first = replace(
            first, freshness=(replace(first.freshness[0], fresh_until=now + timedelta(seconds=1)),)
        )
    else:
        # Genuine signed witness time is checked, with no mutable witness fabrication.
        with pytest.raises(ValueError):
            first.require_time(first.credential.expires_at)
        return
    current = replace(
        first,
        lease=first.lease.model_copy(update={"expires_at": now + timedelta(seconds=90)}),
        grants=(first.grants[0].model_copy(update={"expires_at": now + timedelta(seconds=90)}),),
        freshness=(replace(first.freshness[0], fresh_until=now + timedelta(seconds=90)),),
    )
    current.require_time(now + timedelta(seconds=2))
    with pytest.raises(ValueError):
        first.require_time(now + timedelta(seconds=2))


async def test_none_requires_an_actual_registered_no_ttl_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await protection(monkeypatch)
    now = value.observed_at
    unknown = replace(value.freshness[0], fresh_until=None)
    with pytest.raises(ValueError):
        replace(value, freshness=(unknown,)).require_time(now)
    no_ttl = unknown.policy.model_copy(update={"freshness_seconds": None})
    replace(value, freshness=(replace(unknown, policy=no_ttl),)).require_time(now)


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
    now = datetime.now(UTC)
    candidate = PlanModelCandidateWindow(
        "fixture-model",
        "a" * 64,
        "b" * 64,
        ModelHealth(
            status="healthy",
            checked_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(seconds=1),
        ),
        EvaluationEvidence(
            profile="routine",
            suite_version="v1",
            artifact_reference="fixture.eval",
            score=Decimal(1),
            conformance_passed=True,
            evaluated_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(seconds=20),
        ),
    )
    slot = case.cycle.admission.slots[4].child
    original = PlanChildWindow(slot.binding, slot.quota, "ordinary", None, (candidate,))
    original.require_time(now)
    with pytest.raises(ValueError):
        original.require_time(now + timedelta(seconds=2))


async def test_late_fixture_call_mints_real_witness_without_renewing_its_original_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.tests.unit import cycle_prerequisite_fixture as fixture

    case = deliverable_case(monkeypatch)
    old_import = datetime.now(UTC) - timedelta(minutes=10)
    monkeypatch.setattr(fixture, "NOW", old_import)
    before = datetime.now(UTC)
    credential = await signed_identity(case.identity)
    after = datetime.now(UTC)
    assert credential.identity == case.identity
    assert before - timedelta(seconds=11) <= credential.issued_at <= after
    assert (
        before + timedelta(seconds=119) <= credential.expires_at <= after + timedelta(seconds=120)
    )
    captured = credential.issued_at, credential.expires_at
    credential.require_time(after)
    with pytest.raises(ValueError):
        credential.require_time(credential.expires_at)
    assert captured == (credential.issued_at, credential.expires_at)
    assert old_import == fixture.NOW


def test_late_fixture_lease_uses_only_call_clock_and_same_sixty_second_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.tests.unit import cycle_prerequisite_fixture as fixture

    case = deliverable_case(monkeypatch)
    monkeypatch.setattr(fixture, "NOW", datetime.now(UTC) - timedelta(minutes=10))
    before = datetime.now(UTC)
    lease = own_lease(case)
    after = datetime.now(UTC)
    assert before + timedelta(seconds=60) <= lease.expires_at <= after + timedelta(seconds=60)
    assert lease.expires_at == case.work.lease_until
