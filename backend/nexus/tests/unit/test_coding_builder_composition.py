"""Concrete full10 roles cannot inherit generic/old6 native permission."""

from pathlib import Path

import pytest

from nexus.builder.coding_templates import CodingBuilderServices
from nexus.company.management.coding_publication_origin import CodingPublicationOriginReader
from nexus.tests.unit.coding_publication_fixture import graph


async def test_full_family_data_is_not_a_concrete_builder_service(tmp_path: Path) -> None:
    value = await graph(tmp_path)
    reader = CodingPublicationOriginReader(
        value.private.factory,
        value.catalog,
        value.private.sources.artifacts,
        value.private.sources.freshness,
        rules=value.rules,
        recipe=value.prepared.input_recipe,
    )
    with pytest.raises(ValueError):
        CodingBuilderServices(reader, ())


async def test_only_actual_concrete_e_composite_has_shape_not_native_permission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    from nexus.builder.contained_intent_check import ContainedParentIntentCheck
    from nexus.execution.effect_store import EffectStore
    from nexus.execution.intent_checks import CompositeBeforeIntentCheck
    from nexus.execution.nexus_intent_gate import _shape
    from nexus.execution.runtime_contracts import AttemptKind, ExecutionDeniedError
    from nexus.tests.unit.test_coding_builder_guard import guard_case

    data = await guard_case(tmp_path, monkeypatch)
    v = data.value
    slot = v.origin_reader.admission.slots[5]
    for key in (
        "company_id",
        "task_id",
        "trace_id",
        "run_id",
        "actor_id",
        "workspace_id",
        "workflow_name",
        "workflow_version",
        "model_profile",
        "model_registry_version",
    ):
        setattr(v.builder_work, key, getattr(slot.child.binding, key))
    effects = EffectStore(v.private.factory, management_catalog=v.catalog)
    good = CompositeBeforeIntentCheck((data.guard, ContainedParentIntentCheck(data.contained)))
    kind: AttemptKind = "tool_attempts"
    args = (
        v.private.factory,
        effects,
        v.catalog,
        v.builder_work,
        v.builder_lease,
        v.builder_credential.identity,
        v.builder_action,
        kind,
    )
    assert _shape(*args, good)
    for wrong in (
        None,
        AsyncMock(),
        CompositeBeforeIntentCheck((data.original, ContainedParentIntentCheck(data.contained))),
    ):
        with pytest.raises(ExecutionDeniedError):
            _shape(*args, wrong)
    assert v.native.hold.actual_usd == data.proof.origin.actual_usd
    # Shape success never calls EffectStore.begin or grants a permit/debits a quota.


@pytest.mark.parametrize("index", [2, 3, 4, 7, 8, 9])
async def test_unimplemented_full_family_roles_stay_denied_before_fallback(
    tmp_path: Path, index: int
) -> None:
    from nexus.execution.effect_store import EffectStore
    from nexus.execution.nexus_coding_intent_gate import _installed
    from nexus.execution.runtime_contracts import ExecutionDeniedError
    from nexus.execution.runtime_models import ExecutionWork

    value = await graph(tmp_path)
    effects = EffectStore(value.private.factory, management_catalog=value.catalog)
    slot = value.catalog.nexus_coding_admission.slots[index]
    work = ExecutionWork(company_id=value.catalog.company_id, task_id=slot.work.task_id)
    with pytest.raises(ExecutionDeniedError):
        _installed(effects, work)
