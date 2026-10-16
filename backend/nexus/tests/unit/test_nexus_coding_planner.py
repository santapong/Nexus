"""Real full-profile planning graph/native-row mapping with supplied SQL delivery only."""

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid5

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.nexus_coding_admission import NexusCodingAdmission
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.planning_content import PlanningContent, PlanningTask
from nexus.company.management.planning_proposal_bridge import (
    PlanningProposalTemplate,
    PlanningTaskSlot,
    map_content,
)
from nexus.execution.nexus_cycle_partition import read_current_nexus_family_locked
from nexus.execution.planning_application import compose_planning_application
from nexus.tests.unit.nexus_cycle_fixture import NOW
from nexus.tests.unit.test_nexus_coding_admission import planning_origin
from nexus.tests.unit.test_nexus_coding_catalog import coding_case, coding_configuration
from nexus.tests.unit.test_planning_application import (
    TEST_SIGNER,
    SuppliedCredential,
    application_settings,
)


def base_plan(value: NexusCodingAdmission) -> PlanRevision:
    payload = value.payload("planning")
    digest = canonical_sha256(payload)
    return PlanRevision(
        company_id=value.company_id,
        plan_id=value.plan_id,
        plan_revision_id=uuid5(value.plan_id, "plan:1:" + digest),
        revision=1,
        sha256=digest,
        payload=payload,
        proposed_by=value.procedure.binding.actor_id,
        recorded_at=NOW,
    )


def template() -> PlanningProposalTemplate:
    value, _ = coding_case()
    return PlanningProposalTemplate(
        base_plan=base_plan(value),
        revision="coding-mapping.v1",
        nexus_coding_admission=value,
        slots=tuple(
            PlanningTaskSlot(
                key=slot.role,
                allocation=slot.child,
                department=slot.work.department,
                required_dependencies=slot.work.depends_on,
            )
            for slot in value.slots[1:]
        ),
    )


def test_actual_mapper_preserves_bootstrap_root_digest_and_all_ten_authority_slots() -> None:
    fixed = template()
    value = fixed.nexus_coding_admission
    assert value is not None
    content = PlanningContent(
        tasks=tuple(
            PlanningTask(
                key=slot.key,
                title="Model proposed " + slot.key,
                description="Untrusted planning DATA",
                acceptance=("not authority",),
                depends_on=(),
                evidence_ids=(),
            )
            for slot in fixed.slots
        ),
        questions=(),
    )
    origin = planning_origin(value).model_copy(
        update={
            "mapping_revision": fixed.revision,
            "mapping_sha256": canonical_sha256(fixed),
            "content_sha256": canonical_sha256(content),
        }
    )
    mapped = map_content(content, origin, fixed)
    assert mapped.procedure == fixed.base_plan.payload.procedure
    assert mapped.coding_admission_sha256 == fixed.base_plan.payload.coding_admission_sha256
    assert mapped.plan.items[0] == fixed.base_plan.payload.plan.items[0]
    assert len(mapped.children) == 10 and len(mapped.verification) == 2
    assert tuple(row.acceptance for row in mapped.plan.items) == tuple(
        slot.work.acceptance for slot in value.slots
    )


async def test_same_real_application_and_approved_row_loader_use_coding_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.tests.unit.test_planning_lifecycle import native_bundle

    configured = coding_configuration(tmp_path)
    services = compose_planning_application(
        async_sessionmaker[AsyncSession](),
        configured,
        application_settings(),
        SuppliedCredential(),
        SecretStr(TEST_SIGNER),
    )
    bundle = await native_bundle(services.lifecycle, monkeypatch)
    assert bundle.reader is bundle.plans.planning_reader
    assert bundle.reader.template.nexus_admission is None
    assert bundle.reader.template.nexus_coding_admission == configured.admission
    assert bundle.base.payload.coding_admission_sha256 == canonical_sha256(configured.admission)
    assert services.management.planning_lifecycle is services.planning.lifecycle
    assert len(bundle.reader.template.slots) == 9
    services.require_composition()


@pytest.mark.parametrize("stage", ["planning", "execution"])
async def test_current_actual_family_checks_all_two_or_eleven_rows(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    from typing import cast

    from nexus.company.management.nexus_cycle_admission import NexusStage
    from nexus.tests.unit import nexus_family_fixture as fixture

    monkeypatch.setattr(fixture, "case", coding_case)
    monkeypatch.setattr(fixture, "base", base_plan)
    monkeypatch.setattr(fixture, "origin", planning_origin)
    value = fixture.family(monkeypatch, cast(NexusStage, stage))
    record = await read_current_nexus_family_locked(
        value.session,
        value.control,
        value.work,
        value.identity,
        admission=value.admission,
        catalog=value.catalog,
    )
    assert len(value.executions) == (2 if stage == "planning" else 11)
    assert value.executions[0].model_requests_delegated == (1 if stage == "planning" else 5)
    assert record.payload.coding_admission_sha256 == canonical_sha256(value.admission)


def test_changed_future_slot_changes_durable_bootstrap_hash_before_registration() -> None:
    value, catalog = coding_case()
    first = value.payload("planning")
    raw = value.model_dump()
    raw["slots"][1]["child"]["allocation_usd"] *= 2
    raw["slots"][1]["work"]["budget_usd"] *= 2
    changed = type(value).model_validate(raw)
    changed_catalog = catalog.model_copy(update={"nexus_coding_admission": changed})
    from nexus.company.management.nexus_coding_catalog import select_configured_nexus_plan

    with pytest.raises(ValueError):
        select_configured_nexus_plan(changed_catalog, first)


async def test_new_profile_bootstrap_never_skips_actual_owner_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock

    from nexus.company.access import CompanyControlScope, VerifiedIdentity
    from nexus.company.management import nexus_plan_admission as owner
    from nexus.company.management.planning_native_facts import read_end
    from nexus.harness.journal_models import CompanyControl

    config = coding_configuration(tmp_path)
    store = ManagementPlanStore(async_sessionmaker[AsyncSession](), config.catalog)
    binding = config.admission.procedure.binding
    identity = VerifiedIdentity(principal_id=binding.actor_id, workspace_id=binding.workspace_id)
    scope = CompanyControlScope(
        company_id=binding.company_id,
        principal_id=binding.actor_id,
        operation_id=uuid5(binding.task_id, "test-owner"),
        trace_id=binding.trace_id,
    )
    delivery = AsyncMock(side_effect=AssertionError("Invalid owner reached native metadata"))
    monkeypatch.setattr(owner, "validate_plan", delivery)
    with pytest.raises(ValueError):
        await owner.capture_nexus_owner_locked(
            store,
            MagicMock(),
            CompanyControl(owner_id=binding.actor_id),
            scope,
            identity,
            config.admission.payload("planning"),
            None,
            end_us=read_end(),
        )
    delivery.assert_not_awaited()
