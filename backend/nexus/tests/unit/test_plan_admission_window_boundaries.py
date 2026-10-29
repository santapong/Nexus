"""Retained model alternatives, explicit source policies and sealed credential time boundaries."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.brain.base import BrainReadScope
from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.management.plan_admission_candidates import capture_child_window
from nexus.company.management.plan_admission_capture import _capture_plan_metadata_locked
from nexus.company.management.plan_admission_metadata import capture_sources
from nexus.company.management.plan_support import validate_plan
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.notifications.worker_identity import WorkerIdentityDeniedError
from nexus.tests.unit.plan_admission_fixture_data import (
    COMPANY,
    NOW,
    OWNER,
    WORKSPACE,
    ordinary_fixture,
)
from nexus.tests.unit.plan_admission_fixture_session import MetadataSession, qualifier
from nexus.tests.unit.plan_admission_witness_fixture import (
    admission_case_clock as admission_case_clock,
)
from nexus.tests.unit.plan_admission_witness_fixture import witness


def test_model_fallback_is_any_retained_eligible_alternative_not_global_min() -> None:
    data = ordinary_fixture()
    model = data.catalog.models.models[1]
    later = model.model_copy(
        update={
            "registry_id": "presentation-fallback",
            "model_id": "presentation-fallback",
            "health": model.health.model_copy(update={"expires_at": NOW + timedelta(seconds=60)}),
            "evaluations": (
                model.evaluations[0].model_copy(update={"expires_at": NOW + timedelta(seconds=60)}),
            ),
        }
    )
    catalog = data.catalog.model_copy(
        update={
            "models": data.catalog.models.model_copy(
                update={"models": (*data.catalog.models.models, later)}
            )
        }
    )
    retained = capture_child_window(catalog, data.payload.children[2], NOW)
    assert len(retained.candidates) == 2
    retained.require_time(NOW + timedelta(seconds=6))
    with pytest.raises(ManagementDeniedError):
        retained.require_time(NOW + timedelta(seconds=61))


def test_future_only_model_cannot_rescue_the_original_expired_witness() -> None:
    data = ordinary_fixture()
    model = data.catalog.models.models[1]
    future = model.model_copy(
        update={
            "registry_id": "future",
            "model_id": "future",
            "health": model.health.model_copy(
                update={
                    "checked_at": NOW + timedelta(seconds=6),
                    "expires_at": NOW + timedelta(seconds=60),
                }
            ),
            "evaluations": (
                model.evaluations[0].model_copy(
                    update={
                        "evaluated_at": NOW + timedelta(seconds=6),
                        "expires_at": NOW + timedelta(seconds=60),
                    }
                ),
            ),
        }
    )
    catalog = data.catalog.model_copy(
        update={
            "models": data.catalog.models.model_copy(
                update={"models": (*data.catalog.models.models, future)}
            )
        }
    )
    retained = capture_child_window(catalog, data.payload.children[2], NOW)
    assert len(retained.candidates) == 1
    with pytest.raises(ManagementDeniedError):
        retained.require_time(NOW + timedelta(seconds=7))


@pytest.mark.parametrize("value", [False, 1.0, "1"])
def test_raw_copied_quota_is_rejected_before_serialization(value: object) -> None:
    data = ordinary_fixture()
    child = data.payload.children[0]
    child = child.model_copy(
        update={"quota": child.quota.model_copy(update={"model_requests": value})}
    )
    with pytest.raises(ValidationError):
        capture_child_window(data.catalog, child, NOW)


async def test_no_ttl_requires_real_registered_policy_and_never_materializes_body() -> None:
    data = ordinary_fixture()
    db = MetadataSession(data)
    scope = BrainReadScope(
        company_id=COMPANY,
        workspace_id=WORKSPACE,
        principal_id=OWNER,
        operation_id=UUID(int=7),
        trace_id=UUID(int=8),
    )
    data.head.fresh_until = None
    with pytest.raises(AcceptanceDeniedError):
        await capture_sources(db.session, scope, (data.source.resource_id,), qualifier(data), NOW)
    data.policy = data.policy.model_copy(update={"freshness_seconds": None})
    result = await capture_sources(
        db.session, scope, (data.source.resource_id,), qualifier(data), NOW
    )
    assert len(result) == 1 and result[0].qualified.policy.freshness_seconds is None
    assert result[0].qualified.fresh_until is None and db.body_reads == 0
    data.source.external_key = "not-registered"
    with pytest.raises(AcceptanceDeniedError):
        await capture_sources(db.session, scope, (data.source.resource_id,), qualifier(data), NOW)


async def test_retained_genuine_credential_and_scope_cannot_be_renewed_by_other_facts() -> None:
    data = ordinary_fixture()
    db = MetadataSession(data)
    fresh = qualifier(data)
    charters = await validate_plan(
        db.session, data.control, data.scope, data.identity, data.payload, data.catalog, fresh
    )
    window = await _capture_plan_metadata_locked(
        db.session,
        data.control,
        data.scope,
        data.identity,
        data.payload,
        data.catalog,
        charters,
        fresh,
        credential=await witness(data),
    )
    with pytest.raises(WorkerIdentityDeniedError):
        window.require_time(NOW + timedelta(seconds=601))
    with pytest.raises(ManagementDeniedError):
        window.require_same_scope(replace(window, policy_version="changed"))
    with pytest.raises(ManagementDeniedError):
        replace(window, owner_id=UUID(int=999)).require_time(NOW)


async def test_first_grant_deadline_is_retained_when_current_metadata_looks_longer_lived() -> None:
    # This >50-line scenario keeps both genuine captures and the original late deadline together.
    data = ordinary_fixture()
    model = data.catalog.models.models[1]
    long = model.model_copy(
        update={
            "health": model.health.model_copy(update={"expires_at": NOW + timedelta(hours=1)}),
            "evaluations": (
                model.evaluations[0].model_copy(update={"expires_at": NOW + timedelta(hours=1)}),
            ),
        }
    )
    data.catalog = data.catalog.model_copy(
        update={
            "models": data.catalog.models.model_copy(
                update={"models": (data.catalog.models.models[0], long)}
            )
        }
    )
    db = MetadataSession(data)
    fresh = qualifier(data)
    credential = await witness(data)
    charters = await validate_plan(
        db.session, data.control, data.scope, data.identity, data.payload, data.catalog, fresh
    )
    first = await _capture_plan_metadata_locked(
        db.session,
        data.control,
        data.scope,
        data.identity,
        data.payload,
        data.catalog,
        charters,
        fresh,
        credential=credential,
    )
    # Pure metadata-return simulation, not an actual grant update or owner approval.
    for grant in data.grants:
        if grant.expires_at is not None:
            grant.expires_at = NOW + timedelta(hours=1)
    current = await _capture_plan_metadata_locked(
        db.session,
        data.control,
        data.scope,
        data.identity,
        data.payload,
        data.catalog,
        charters,
        fresh,
        credential=credential,
    )
    first.require_same_scope(current)
    current.require_time(NOW + timedelta(seconds=6))
    with pytest.raises(ManagementDeniedError):
        first.require_time(NOW + timedelta(seconds=6))
    assert any(row.expires_at == NOW + timedelta(seconds=5) for row in first.grants)


def test_zero_model_quota_ordinary_role_still_requires_its_actual_profile_window() -> None:
    data = ordinary_fixture()
    child = data.payload.children[2]
    child = child.model_copy(update={"quota": child.quota.model_copy(update={"model_requests": 0})})
    retained = capture_child_window(data.catalog, child, NOW)
    assert retained.kind == "ordinary"
    with pytest.raises(ManagementDeniedError):
        retained.require_time(NOW + timedelta(seconds=6))


async def test_capture_rejects_unsealed_credential_before_any_qualification() -> None:
    from nexus.company.management.plan_admission_capture import capture_plan_admission_locked

    data = ordinary_fixture()
    db = MetadataSession(data)
    with pytest.raises(ManagementDeniedError):
        await capture_plan_admission_locked(
            db.session,
            data.control,
            data.scope,
            data.identity,
            data.payload,
            data.catalog,
            qualifier(data),
            credential=object(),  # type: ignore[arg-type]
        )
    assert db.statements == [] and db.body_reads == 0


async def test_profile_capture_does_not_switch_to_future_model_during_metadata_await(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    # This >50-line nominated-clock scenario keeps real validation and the future candidate apart.
    data = ordinary_fixture()
    for grant in data.grants:
        grant.expires_at = None
    model = data.catalog.models.models[1]
    future = model.model_copy(
        update={
            "registry_id": "future-during-capture",
            "model_id": "future-during-capture",
            "health": model.health.model_copy(
                update={
                    "checked_at": NOW + timedelta(seconds=6),
                    "expires_at": NOW + timedelta(seconds=60),
                }
            ),
            "evaluations": (
                model.evaluations[0].model_copy(
                    update={
                        "evaluated_at": NOW + timedelta(seconds=6),
                        "expires_at": NOW + timedelta(seconds=60),
                    }
                ),
            ),
        }
    )
    data.catalog = data.catalog.model_copy(
        update={
            "models": data.catalog.models.model_copy(
                update={"models": (*data.catalog.models.models, future)}
            )
        }
    )
    db = MetadataSession(data)
    fresh = qualifier(data)
    charters = await validate_plan(
        db.session, data.control, data.scope, data.identity, data.payload, data.catalog, fresh
    )

    async def later_metadata(query: object) -> object:
        result = await db.scalar(query)
        if "min(company_brain_source_heads.fresh_until)" in str(query):
            db.now = NOW + timedelta(seconds=7)
        return result

    monkeypatch.setattr(db.session, "scalar", AsyncMock(side_effect=later_metadata))
    with pytest.raises(ManagementDeniedError):
        await _capture_plan_metadata_locked(
            db.session,
            data.control,
            data.scope,
            data.identity,
            data.payload,
            data.catalog,
            charters,
            fresh,
            credential=await witness(data),
        )
    assert db.body_reads == 0


async def test_unused_declared_charter_deadline_is_retained_by_legacy_aggregate_scope() -> None:
    from nexus.tests.unit.plan_admission_fixture_values import unused_charter_deadline

    # This >50-line scenario isolates all-charter minima without granting unused-role READ.
    data = ordinary_fixture()
    for grant in data.grants:
        grant.expires_at = None
    model = data.catalog.models.models[1]
    long = model.model_copy(
        update={
            "health": model.health.model_copy(update={"expires_at": NOW + timedelta(hours=1)}),
            "evaluations": (
                model.evaluations[0].model_copy(update={"expires_at": NOW + timedelta(hours=1)}),
            ),
        }
    )
    data.catalog = data.catalog.model_copy(
        update={
            "models": data.catalog.models.model_copy(
                update={"models": (data.catalog.models.models[0], long)}
            )
        }
    )
    unused = unused_charter_deadline(data)
    db = MetadataSession(data)
    fresh = qualifier(data)
    charters = await validate_plan(
        db.session, data.control, data.scope, data.identity, data.payload, data.catalog, fresh
    )
    assert len(charters) == 5 and len(data.payload.children) == 4
    window = await _capture_plan_metadata_locked(
        db.session,
        data.control,
        data.scope,
        data.identity,
        data.payload,
        data.catalog,
        charters,
        fresh,
        credential=await witness(data),
    )
    window.require_time(NOW)
    assert all(grant.resource_id != unused for grant in window.grants)
    assert len(window.sources) == 1 and db.body_reads == 0
    with pytest.raises(ManagementDeniedError):
        window.require_time(NOW + timedelta(seconds=6))
    assert window.aggregate_grant_expiry == NOW + timedelta(seconds=5)
