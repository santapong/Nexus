"""A fixed no-model sender identity is eligibility metadata, never send authority."""

# TASK: Bind one explicit notification-only profile to the original catalog and target.
# FILES: NEW native_profile_contracts.py, native_profile_checks.py and this unit file.
# DONE: Exact zero-model sender admits; corrupt complete tuples and other effects deny.
# RISK: High admission boundary; Root separately integrates owner/ancestry/current gates.

from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plan_support import NamedPlanResource, PlanAdmissionCatalog
from nexus.company.management.plans import PlanPayload, RunBinding
from nexus.company.notifications.native_profile_checks import (
    native_notification_profile,
    require_notification_action,
    require_notification_plan,
    validate_notification_profiles,
)
from nexus.company.notifications.native_profile_contracts import NativeNotificationProfile
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.runtime_contracts import AttemptKind, AttemptQuota
from nexus.harness.standing_contracts import ToolPermission
from nexus.tests.unit.test_company_foundation import proposal
from nexus.tests.unit.test_company_management_plans import payload


def notification_plan() -> tuple[PlanAdmissionCatalog, PlanPayload]:
    """One new declaration has no model, owner credential, approval or execution permit."""
    original = payload()
    registry = ModelRegistry(
        company_id=original.company_id, revision="native-catalog-v1", pricebook_version="p1"
    )
    profile = _profile(registry)
    child = original.children[0].model_copy(
        update={
            "binding": _notification_binding(original.children[0].binding, profile),
            "quota": AttemptQuota(
                model_requests=0, tool_attempts=1, rework_rounds=0, plan_revisions=0
            ),
        }
    )
    data = original.model_copy(
        update={
            "children": (child,),
            "verification": (),
            "plan": original.plan.model_copy(update={"items": (original.plan.items[0],)}),
            "procedure": original.procedure.model_copy(
                update={
                    "binding": _notification_binding(original.procedure.binding, profile),
                    "quota": AttemptQuota(model_requests=0),
                }
            ),
        }
    )
    return _catalog(registry, profile), data


def _catalog(registry: ModelRegistry, profile: NativeNotificationProfile) -> PlanAdmissionCatalog:
    return PlanAdmissionCatalog.model_validate(
        {
            "company_id": registry.company_id,
            "models": registry,
            "admitted_profiles": frozenset(),
            "check_recipes": frozenset(),
            "tools": (
                ToolPermission(
                    tool="company.owner-notification.send.v1",
                    tool_version="v1",
                    resource=profile.target_symbol,
                ),
            ),
            "resources": (
                NamedPlanResource(symbol=profile.target_symbol, resource=profile.target_resource),
            ),
            "notification_profiles": (profile,),
        }
    )


def _profile(registry: ModelRegistry) -> NativeNotificationProfile:
    return NativeNotificationProfile(
        company_id=registry.company_id,
        execution_profile="notification.native.v1",
        workflow_name="internal.owner-notification",
        registry_revision=registry.revision,
        registry_sha256=canonical_sha256(registry),
        target_symbol="company.owner-notifications",
        target_resource=ResourceRef(company_id=registry.company_id, resource_id=UUID(int=810)),
    )


def _notification_binding(binding: RunBinding, profile: NativeNotificationProfile) -> RunBinding:
    """Keep fixture identity metadata changes separate from any real registered state."""
    return binding.model_copy(
        update={
            "workflow_name": profile.workflow_name,
            "workflow_version": profile.workflow_version,
            "model_profile": profile.execution_profile,
            "model_registry_version": profile.registry_revision,
        }
    )


def test_empty_model_catalog_admits_only_one_exact_notification_declaration() -> None:
    catalog, data = notification_plan()
    PlanPayload.model_validate_json(data.model_dump_json())
    require_notification_plan(catalog, data)
    selected = native_notification_profile(catalog, data.children[0])
    assert selected == catalog.notification_profiles[0]
    assert catalog.models.models == ()
    old = catalog.model_copy(update={"notification_profiles": ()})
    assert "notification_profiles" not in old.model_dump(mode="json")
    assert native_notification_profile(old, data.children[0]) is None
    assert native_notification_profile(catalog, payload().children[0]) is None


@pytest.mark.parametrize(
    "field,bad",
    [
        ("workflow_name", "internal.report"),
        ("workflow_version", "v2"),
        ("execution_profile", "engineering.native.v1"),
        ("registry_sha256", "invalid"),
        ("target_symbol", ""),
        ("company_id", UUID(int=900)),
    ],
)
def test_profile_contract_rejects_unsupported_or_cross_company_identity(
    field: str,
    bad: object,
) -> None:
    row = _profile(
        ModelRegistry(
            company_id=payload().company_id, revision="native-catalog-v1", pricebook_version="p1"
        )
    )
    with pytest.raises(ValidationError):
        NativeNotificationProfile.model_validate(row.model_dump() | {field: bad})


@pytest.mark.parametrize("failure", ["duplicate", "digest", "revision", "workflow", "foreign"])
def test_corrupt_unselected_complete_tuple_denies_before_child_selection(failure: str) -> None:
    catalog, _ = notification_plan()
    row = catalog.notification_profiles[0]
    updates: dict[str, dict[str, object]] = {
        "digest": {"registry_sha256": "f" * 64},
        "revision": {"registry_revision": "other"},
        "workflow": {"workflow_name": "engineering.verify"},
        "foreign": {"company_id": UUID(int=999)},
    }
    profiles = (row, row) if failure == "duplicate" else (row.model_copy(update=updates[failure]),)
    with pytest.raises(ValueError):
        validate_notification_profiles(catalog.models, profiles)
    corrupted = catalog.model_copy(update={"notification_profiles": profiles})
    with pytest.raises(ValueError):
        PlanAdmissionCatalog.model_validate_json(corrupted.model_dump_json())
    with pytest.raises(ValueError):
        native_notification_profile(corrupted, payload().children[0])


@pytest.mark.parametrize("bad", [False, True, 1.0, "0"])
def test_copied_coerced_quota_cannot_become_native_zero_model_metadata(bad: object) -> None:
    catalog, data = notification_plan()
    child = data.children[0]
    corrupted = child.model_copy(
        update={"quota": child.quota.model_copy(update={"model_requests": bad})}
    )
    with pytest.raises(ValueError):
        native_notification_profile(catalog, corrupted)


@pytest.mark.parametrize("bad", [False, True, 1.0, "0"])
def test_copied_procedure_quota_cannot_be_normalized_before_sender_plan_check(bad: object) -> None:
    catalog, data = notification_plan()
    root = data.procedure
    corrupted = data.model_copy(
        update={
            "procedure": root.model_copy(
                update={"quota": root.quota.model_copy(update={"model_requests": bad})}
            )
        }
    )
    with pytest.raises(ValueError):
        require_notification_plan(catalog, corrupted)


@pytest.mark.parametrize("field", ["tool_attempts", "rework_rounds", "plan_revisions"])
def test_raw_non_model_quota_fields_also_require_exact_integers(field: str) -> None:
    catalog, data = notification_plan()
    child = data.children[0]
    corrupted = child.model_copy(update={"quota": child.quota.model_copy(update={field: False})})
    with pytest.raises(ValueError):
        native_notification_profile(catalog, corrupted)


def test_model_default_catalog_bytes_do_not_gain_notification_profile_key() -> None:
    registry = ModelRegistry(
        company_id=payload().company_id, revision="native-catalog-v1", pricebook_version="p1"
    )
    data = {
        "company_id": registry.company_id,
        "models": registry,
        "admitted_profiles": frozenset(),
        "check_recipes": frozenset(),
    }
    old = PlanAdmissionCatalog.model_validate(data)
    explicit_empty = PlanAdmissionCatalog.model_validate(data | {"notification_profiles": ()})
    assert old.model_dump_json() == explicit_empty.model_dump_json()
    assert canonical_sha256(old) == canonical_sha256(explicit_empty)
    assert "notification_profiles" not in old.model_dump(mode="json")


@pytest.mark.parametrize("failure", ["revision", "workflow", "company", "quota", "tool", "target"])
def test_partial_sender_selection_cannot_escape_exact_configured_identity(failure: str) -> None:
    catalog, data = notification_plan()
    child = data.children[0]
    if failure == "quota":
        child = child.model_copy(update={"quota": AttemptQuota(model_requests=1)})
    elif failure in {"revision", "workflow", "company"}:
        changes: dict[str, dict[str, object]] = {
            "revision": {"model_registry_version": "other"},
            "workflow": {"workflow_name": "internal.report"},
            "company": {"company_id": UUID(int=999)},
        }
        child = child.model_copy(
            update={"binding": child.binding.model_copy(update=changes[failure])}
        )
    else:
        catalog = catalog.model_copy(
            update={"tools": ()}
            if failure == "tool"
            else {
                "resources": (
                    catalog.resources[0].model_copy(
                        update={
                            "resource": ResourceRef(
                                company_id=data.company_id, resource_id=UUID(int=999)
                            )
                        }
                    ),
                )
            }
        )
    with pytest.raises(ValueError):
        native_notification_profile(catalog, child)


@pytest.mark.parametrize("failure", ["missing_resource", "duplicate_resource", "duplicate_tool"])
def test_copied_ambiguous_or_missing_target_mapping_cannot_select_sender(failure: str) -> None:
    catalog, data = notification_plan()
    updates: dict[str, dict[str, object]] = {
        "missing_resource": {"resources": ()},
        "duplicate_resource": {"resources": catalog.resources * 2},
        "duplicate_tool": {"tools": catalog.tools * 2},
    }
    with pytest.raises(ValueError):
        native_notification_profile(catalog.model_copy(update=updates[failure]), data.children[0])


@pytest.mark.parametrize("failure", ["parent", "parent_identity", "mixed", "edge", "foreign"])
def test_sender_plan_requires_one_child_no_verification_and_zero_model_root(failure: str) -> None:
    catalog, data = notification_plan()
    changes: dict[str, dict[str, object]] = {
        "parent": {"procedure": data.procedure.model_copy(update={"quota": AttemptQuota()})},
        "parent_identity": {
            "procedure": data.procedure.model_copy(
                update={
                    "binding": data.procedure.binding.model_copy(
                        update={"workflow_name": "internal.report"}
                    )
                }
            )
        },
        "mixed": {"children": (data.children[0], payload().children[1])},
        "edge": {"verification": payload().verification},
        "foreign": {"company_id": UUID(int=998)},
    }
    with pytest.raises(ValueError):
        require_notification_plan(catalog, data.model_copy(update=changes[failure]))


@pytest.mark.parametrize(
    "kind,tool,version,target,allowed",
    [
        (
            "tool_attempts",
            "company.owner-notification.send.v1",
            "v1",
            "company.owner-notifications",
            True,
        ),
        (
            "model_requests",
            "company.owner-notification.send.v1",
            "v1",
            "company.owner-notifications",
            False,
        ),
        ("tool_attempts", "model.request.v1", "v1", "model:any", False),
        (
            "tool_attempts",
            "company.owner-notification.send.v1",
            "v2",
            "company.owner-notifications",
            False,
        ),
        ("tool_attempts", "company.owner-notification.send.v1", "v1", "another.target", False),
    ],
)
def test_native_effect_narrows_only_the_registered_sender_tuple(
    kind: AttemptKind,
    tool: str,
    version: str,
    target: str,
    allowed: bool,
) -> None:
    catalog, data = notification_plan()
    action = proposal().model_copy(
        update={"tool": tool, "tool_version": version, "resource": target}
    )
    if allowed:
        assert require_notification_action(catalog, data.children[0], action, kind)
    else:
        with pytest.raises(ValueError):
            require_notification_action(catalog, data.children[0], action, kind)
