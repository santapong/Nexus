"""Future composition only: real ordinary validation, no whole/native/family validator stubs."""

from datetime import timedelta

import pytest

from nexus.company.management.plan_admission_capture import (
    _capture_plan_metadata_locked,
    capture_plan_admission_locked,
)
from nexus.company.management.plan_support import validate_plan
from nexus.company.management.transactions import ManagementDeniedError
from nexus.tests.unit.plan_admission_fixture_data import ordinary_fixture
from nexus.tests.unit.plan_admission_fixture_session import MetadataSession, qualifier
from nexus.tests.unit.plan_admission_witness_fixture import (
    admission_case_clock as admission_case_clock,
)
from nexus.tests.unit.plan_admission_witness_fixture import witness


async def test_later_p_only_expiry_must_not_be_lost_after_real_plan_validation() -> None:
    data = ordinary_fixture()
    db = MetadataSession(data)
    fresh = qualifier(data)
    credential = await witness(data)
    charters = await validate_plan(
        db.session, data.control, data.scope, data.identity, data.payload, data.catalog, fresh
    )
    assert isinstance(charters, dict) and len(charters) == 4
    window = await _capture_plan_metadata_locked(
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
    window.require_time(db.now)
    db.now += timedelta(seconds=6)
    assert data.head.fresh_until is not None and db.now < data.head.fresh_until
    with pytest.raises(ManagementDeniedError):
        window.require_time(db.now)
    assert db.body_reads == 0 and window.execution_pricing_authority == "unqualified"


async def test_public_full_wrapper_does_not_admit_ordinary_or_enable_mixed() -> None:
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
            credential=await witness(data),
        )
    assert any("min(company_brain_resource_access.expires_at)" in sql for sql in db.statements)
    assert db.body_reads == 0
