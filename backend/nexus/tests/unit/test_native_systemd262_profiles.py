"""Exact manager/phase identities preserve old history and grant no execution authority."""

import hashlib
import json
from pathlib import Path

import pytest

from nexus.builder.contained_contracts import ParentObservation, UserManagerObservation
from nexus.builder.contained_discovery import decode_discovery
from nexus.builder.contained_scope import validate_current_scope, validate_issued_scope
from nexus.builder.execution_method import (
    CONTAINED_EXECUTION_METHOD_SHA256,
    CONTAINED_EXECUTION_METHOD_V6_SHA256,
    CONTAINED_EXECUTION_METHOD_V7_SHA256,
    execution_method_candidate,
)
from nexus.builder.issued_parent_identity import (
    CURRENT_ISSUED_PARENT_PROFILES,
    ISSUED_PARENT_262_METHOD_SHA256,
    ISSUED_PARENT_METHOD_SHA256,
    ISSUED_PARENT_PROFILES,
    current_issued_parent_profile,
    issued_parent_profile,
)
from nexus.builder.user_parent_identity import (
    CURRENT_USER_PARENT_262_METHOD_SHA256,
    CURRENT_USER_PARENT_PROFILES,
    USER_PARENT_262_METHOD_SHA256,
    USER_PARENT_METHOD_SHA256,
    USER_PARENT_PROFILES,
    current_root_parent_profile,
    root_parent_profile,
)
from nexus.tests.contained_process_fixture import launch, parent
from nexus.tests.unit.test_contained_discovery import body
from nexus.tests.unit.test_contained_scope import user_manager
from nexus.tests.unit.test_issued_parent_contracts import placement


def manager(version: str) -> UserManagerObservation:
    """Synthetic context; never an issued ownership or permission object."""
    return UserManagerObservation.model_validate(user_manager().model_dump() | {"version": version})


def observation(version: str, issued: bool = False) -> ParentObservation:
    """Use the existing complete comparison fixtures with only an exact daemon version changed."""
    current, context = parent(), manager(version)
    unit = current.unit.model_copy(update={"user_manager": context})
    kernel = current.kernel.model_copy(update={"user_manager": context})
    if not issued:
        return validate_current_scope(current.expectation, unit, kernel, 11_000_000, 12_000_000)
    owned = placement()
    return validate_issued_scope(
        current.expectation,
        unit,
        kernel.model_copy(update={"self_cgroup_path": owned.runtime_path}),
        owned,
        decode_discovery(body(), launch(), runtime_pid=777),
        11_000_000,
        12_000_000,
    )


@pytest.mark.parametrize("version", ["261.2-1", "262-1"])
@pytest.mark.parametrize("issued", [False, True])
def test_exact_version_phase_profile_and_structural_wire(version: str, issued: bool) -> None:
    row = observation(version, issued)
    wanted = (
        current_issued_parent_profile(version) if issued else current_root_parent_profile(version)
    )
    assert (row.provider_version, row.provider_method_sha256) == wanted
    assert row.schema_version == f"nexus.builder.parent-observation.v{3 if issued else 2}"
    assert row.unit.user_manager == row.kernel.user_manager == manager(version)
    assert ParentObservation.model_validate_json(row.model_dump_json()) == row
    assert row.deadline_us == row.unit.active_enter_us + row.unit.runtime_us
    assert row.remaining_us == row.deadline_us - row.observed_end_us


@pytest.mark.parametrize("version", ["261.2-1", "262-1"])
@pytest.mark.parametrize("issued", [False, True])
def test_every_other_version_phase_or_hash_tuple_denies(version: str, issued: bool) -> None:
    row = observation(version, issued)
    profiles = (
        *USER_PARENT_PROFILES.values(),
        *ISSUED_PARENT_PROFILES.values(),
        *CURRENT_USER_PARENT_PROFILES.values(),
        *CURRENT_ISSUED_PARENT_PROFILES.values(),
    )
    historical = issued_parent_profile(version) if issued else root_parent_profile(version)
    for provider, digest in profiles:
        if (provider, digest) in ((row.provider_version, row.provider_method_sha256), historical):
            continue
        for patch in (
            {"provider_version": provider, "provider_method_sha256": digest},
            {"provider_version": provider},
            {"provider_method_sha256": digest},
        ):
            with pytest.raises(ValueError):
                ParentObservation.model_validate(row.model_dump() | patch)


@pytest.mark.parametrize("version", ["261.2-1", "262-1"])
@pytest.mark.parametrize("issued", [False, True])
@pytest.mark.parametrize("side", ["unit", "kernel"])
def test_mixed_actual_manager_facts_deny_before_profile_interpretation(
    version: str, issued: bool, side: str
) -> None:
    row = observation(version, issued)
    other = manager("262-1" if version == "261.2-1" else "261.2-1")
    changed = getattr(row, side).model_copy(update={"user_manager": other})
    with pytest.raises(ValueError, match="manager observations differ"):
        ParentObservation.model_validate(row.model_copy(update={side: changed}))


@pytest.mark.parametrize("issued", [False, True])
@pytest.mark.parametrize("side", ["unit", "kernel", "both"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "262-2"),
        ("version", "262-1.extra"),
        ("version", None),
        ("version", ["262-1"]),
        ("uid", 1001),
        ("uid", 0),
        ("uid", True),
        ("uid", 1000.0),
        ("uid", 2**32),
        ("manager", "system"),
        ("query_route", "caller_bus"),
    ],
)
def test_copied_context_cannot_bypass_closed_context_or_profile_checks(
    issued: bool, side: str, field: str, value: object
) -> None:
    row = observation("262-1", issued)
    copied = row.unit.user_manager.model_copy(update={field: value})
    unit = row.unit.model_copy(update={"user_manager": copied}) if side != "kernel" else row.unit
    kernel = (
        row.kernel.model_copy(update={"user_manager": copied}) if side != "unit" else row.kernel
    )
    with pytest.raises(ValueError):
        ParentObservation.model_validate(row.model_copy(update={"unit": unit, "kernel": kernel}))


def test_262_cannot_inherit_261_provider_defaults() -> None:
    row = observation("262-1").model_dump()
    row.pop("provider_version")
    row.pop("provider_method_sha256")
    with pytest.raises(ValueError, match="provider method differs"):
        ParentObservation.model_validate(row)
    fresh = observation("261.2-1")
    provider, digest = root_parent_profile("261.2-1")
    legacy = ParentObservation.model_validate(
        fresh.model_dump() | {"provider_version": provider, "provider_method_sha256": digest}
    )
    old = legacy.model_dump(exclude={"provider_version", "provider_method_sha256"})
    assert ParentObservation.model_validate(old) == legacy


@pytest.mark.parametrize("issued", [False, True])
@pytest.mark.parametrize("schema", ["unknown", "nexus.builder.parent-observation.v1"])
def test_copied_structural_phase_cannot_bypass_exact_profile(issued: bool, schema: str) -> None:
    row = observation("262-1", issued)
    with pytest.raises(ValueError):
        ParentObservation.model_validate(row.model_copy(update={"schema_version": schema}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("runtime_us", 60_000_000),
        ("randomized_extra_us", 1),
        ("pids", 128),
        ("delegated", False),
        ("send_sigkill", False),
        ("cpu_period_us", 50_000),
    ],
)
def test_262_still_requires_every_original_exact_unit_limit(field: str, value: object) -> None:
    row = observation("262-1")
    with pytest.raises(ValueError):
        validate_current_scope(
            row.expectation,
            row.unit.model_copy(update={field: value}),
            row.kernel,
            11_000_000,
            12_000_000,
        )


@pytest.mark.parametrize("issued", [False, True])
def test_262_never_extends_original_minimum_remaining_window(issued: bool) -> None:
    row = observation("262-1", issued)
    end = row.deadline_us - row.expectation.minimum_remaining_us + 1
    with pytest.raises(ValueError, match="deadline"):
        if issued:
            validate_issued_scope(
                row.expectation,
                row.unit,
                row.kernel,
                placement(),
                decode_discovery(body(), launch(), runtime_pid=777),
                11_000_000,
                end,
            )
        else:
            validate_current_scope(row.expectation, row.unit, row.kernel, 11_000_000, end)


def test_current_native_services_and_verifier_config_reject_legacy_v6(tmp_path: Path) -> None:
    from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
    from nexus.builder.contained_services import ContainmentServices
    from nexus.builder.verification_support import require_containment_configuration

    store = ContainmentEvidenceStore(tmp_path / "sidecars")
    require_containment_configuration(store, CONTAINED_EXECUTION_METHOD_SHA256)
    for previous in (CONTAINED_EXECUTION_METHOD_V6_SHA256, CONTAINED_EXECUTION_METHOD_V7_SHA256):
        with pytest.raises(ValueError, match="configuration"):
            require_containment_configuration(store, previous)
        with pytest.raises(ValueError, match="method"):
            ContainmentServices(parent().expectation, store, method_sha256=previous)


@pytest.mark.parametrize("version", ["262", "262-1.extra", "262-2", "263-1", "261.2-1 ", ""])
def test_profile_selectors_never_accept_version_prefixes(version: str) -> None:
    with pytest.raises(ValueError):
        root_parent_profile(version)
    with pytest.raises(ValueError):
        issued_parent_profile(version)


def test_legacy_three_hashes_and_current_unactivated_candidate() -> None:
    assert (
        USER_PARENT_METHOD_SHA256
        == "19652e7ab8db514c40be246191d60f56fca031dfd8ed0823fcf5a3264285ac5e"
    )
    assert (
        ISSUED_PARENT_METHOD_SHA256
        == "430517e312485b44d95cbabd2291b30d259383a259da4af91c5dc7e7460bc131"
    )
    assert (
        CONTAINED_EXECUTION_METHOD_V6_SHA256
        == "95f3098bda522d1a80eb44746c89aa2913f382cf5605c20fdd7295d33da641c7"
    )
    assert (
        len(
            {
                USER_PARENT_METHOD_SHA256,
                USER_PARENT_262_METHOD_SHA256,
                ISSUED_PARENT_METHOD_SHA256,
                ISSUED_PARENT_262_METHOD_SHA256,
            }
        )
        == 4
    )
    assert CONTAINED_EXECUTION_METHOD_SHA256 != CONTAINED_EXECUTION_METHOD_V6_SHA256
    candidate = execution_method_candidate()
    assert candidate.provider_sha256 == CURRENT_USER_PARENT_262_METHOD_SHA256
    assert candidate.execution_ready is False


def test_retained_actual_261_fourth_case_bytes_and_descriptive_wire_stay_original() -> None:
    path = Path(__file__).parents[1] / "fixtures/issued-parent-v1/fourth-case-parent-failure.json"
    raw = path.read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        == "181822f2c637fa5df507ed0db44f4bc4029ffd8938bfe94e0250cc59c28de080"
    )
    bootstrap = json.loads(raw)["bootstrap"]
    row = ParentObservation.model_validate_json(json.dumps(bootstrap))
    assert row.unit.user_manager.version == row.kernel.user_manager.version == "261.2-1"
    assert row.provider_method_sha256 == USER_PARENT_METHOD_SHA256
    encoded = row.model_dump(mode="json")
    # Controllers are a set in both historical and current DTOs; serialization order is unspecified.
    encoded["kernel"]["controllers"] = sorted(encoded["kernel"]["controllers"])
    bootstrap["kernel"]["controllers"] = sorted(bootstrap["kernel"]["controllers"])
    assert encoded == bootstrap
