"""Pure profile/guard tests; supplied descriptors are never live issued authority."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import nexus.builder.contained_issued_context as owned
from nexus.builder.contained_contracts import ParentObservation
from nexus.builder.contained_process_contracts import require_spawn_ready
from nexus.builder.contained_scope import require_current_parent_profile
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
    CURRENT_USER_PARENT_PROFILES,
    MOUNTINFO64_METHOD_SHA256,
    USER_PARENT_262_METHOD_SHA256,
    USER_PARENT_METHOD_SHA256,
    USER_PARENT_PROFILES,
    current_root_parent_profile,
    root_parent_profile,
)
from nexus.tests.contained_process_fixture import binding, launch, window
from nexus.tests.unit.test_native_systemd262_profiles import observation


def historical(version: str, issued: bool = False) -> ParentObservation:
    value = observation(version, issued)
    provider, digest = issued_parent_profile(version) if issued else root_parent_profile(version)
    return ParentObservation.model_validate(
        value.model_dump() | {"provider_version": provider, "provider_method_sha256": digest}
    )


@pytest.mark.parametrize("version", ["261.2-1", "262-1"])
def test_historical_root_is_readable_but_not_a_fresh_spawn_anchor(version: str) -> None:
    previous = historical(version)
    assert ParentObservation.model_validate_json(previous.model_dump_json()) == previous
    with pytest.raises(ValueError, match=r"current.*profile"):
        require_spawn_ready(
            launch(),
            binding(),
            previous,
            window(),
            monotonic_now_us=12_020_000,
            utc_now=datetime(2026, 10, 15, tzinfo=UTC),
        )


@pytest.mark.parametrize("version", ["261.2-1", "262-1"])
def test_actual_owned_binder_does_not_promote_historical_root(version: str) -> None:
    previous = historical(version)
    # Private, unprepared component data only: no FD is opened and no child is started.
    owner = owned.OwnedStart(owned._ISSUER, binding(), previous.expectation, 13_000_000)
    owner._root_fd = 999
    process = object.__new__(asyncio.subprocess.Process)
    with pytest.raises(ValueError, match=r"current.*profile"):
        owner.bind_spawn(process, previous, 7770)
    assert owner.process is None and owner.runtime_start is None


@pytest.mark.parametrize("version", ["261.2-1", "262-1"])
@pytest.mark.parametrize("issued", [False, True])
def test_historical_current_and_phase_tuples_stay_separate(version: str, issued: bool) -> None:
    previous, current = historical(version, issued), observation(version, issued)
    assert ParentObservation.model_validate_json(previous.model_dump_json()) == previous
    assert (current.provider_version, current.provider_method_sha256) != (
        previous.provider_version,
        previous.provider_method_sha256,
    )
    with pytest.raises(ValueError, match=r"current.*profile"):
        require_current_parent_profile(previous)
    require_current_parent_profile(current)
    for field in ("provider_version", "provider_method_sha256"):
        with pytest.raises(ValueError):
            ParentObservation.model_validate(
                current.model_dump() | {field: getattr(previous, field)}
            )


@pytest.mark.parametrize("version", ["261.2-1", "262-1"])
def test_current_root_passes_actual_spawn_guard_and_component_bind(version: str) -> None:
    current = observation(version)
    require_spawn_ready(
        launch(),
        binding(),
        current,
        window(),
        monotonic_now_us=12_020_000,
        utc_now=datetime(2026, 10, 15, tzinfo=UTC),
    )
    owner = owned.OwnedStart(owned._ISSUER, binding(), current.expectation, 13_000_000)
    owner._root_fd = 999  # Supplied unprepared state only; no actual descriptor/authority.
    process = object.__new__(asyncio.subprocess.Process)
    owner.bind_spawn(process, current, 7770)
    assert owner.process is process and owner.runtime_start == 7770


def test_old_six_digests_and_retained_json_are_not_rehashed_or_relabelled() -> None:
    assert (
        USER_PARENT_METHOD_SHA256,
        USER_PARENT_262_METHOD_SHA256,
        ISSUED_PARENT_METHOD_SHA256,
        ISSUED_PARENT_262_METHOD_SHA256,
        CONTAINED_EXECUTION_METHOD_V6_SHA256,
        CONTAINED_EXECUTION_METHOD_V7_SHA256,
    ) == (
        "19652e7ab8db514c40be246191d60f56fca031dfd8ed0823fcf5a3264285ac5e",
        "14af123683d27a14b9a7a1b347ac75f41ac2d3c1c387eb2ddf9cd46baf83d899",
        "430517e312485b44d95cbabd2291b30d259383a259da4af91c5dc7e7460bc131",
        "180974b5bd52634ebcc98f3629956c9724c27c8488896d868f3560cad2cb7bc9",
        "95f3098bda522d1a80eb44746c89aa2913f382cf5605c20fdd7295d33da641c7",
        "083529a745f4827b10056e839d8f41dc9cfdd7eb8815e4947b26009927073161",
    )
    fixture = (
        Path(__file__).parents[1] / "fixtures/issued-parent-v1/fourth-case-parent-failure.json"
    )
    raw = fixture.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "181822f2c637fa5df507ed0db44f4bc4029ffd8938bfe94e0250cc59c28de080"
    )
    value = ParentObservation.model_validate_json(json.dumps(json.loads(raw)["bootstrap"]))
    assert value.provider_method_sha256 == USER_PARENT_METHOD_SHA256
    missing_defaults = value.model_dump(exclude={"provider_version", "provider_method_sha256"})
    assert ParentObservation.model_validate(missing_defaults) == value


@pytest.mark.parametrize("version", ["261.2-1", "262-1"])
def test_new_current_map_is_distinct_but_original_lookup_is_unchanged(version: str) -> None:
    assert root_parent_profile(version) == USER_PARENT_PROFILES[version]
    assert issued_parent_profile(version) == ISSUED_PARENT_PROFILES[version]
    assert current_root_parent_profile(version) == CURRENT_USER_PARENT_PROFILES[version]
    assert current_issued_parent_profile(version) == CURRENT_ISSUED_PARENT_PROFILES[version]
    profiles = (
        *USER_PARENT_PROFILES.values(),
        *ISSUED_PARENT_PROFILES.values(),
        *CURRENT_USER_PARENT_PROFILES.values(),
        *CURRENT_ISSUED_PARENT_PROFILES.values(),
    )
    assert len({pair[1] for pair in profiles}) == 8
    assert len(MOUNTINFO64_METHOD_SHA256) == 64
    assert CONTAINED_EXECUTION_METHOD_SHA256 not in (
        CONTAINED_EXECUTION_METHOD_V6_SHA256,
        CONTAINED_EXECUTION_METHOD_V7_SHA256,
    )
    candidate = execution_method_candidate()
    assert candidate.execution_ready is False
    assert candidate.provider_sha256 == CURRENT_USER_PARENT_PROFILES["262-1"][1]


@pytest.mark.parametrize("version", ["262", "262-1.extra", "262-2", "263-1", "261.2-1 ", ""])
def test_current_selectors_reject_nonexact_versions(version: str) -> None:
    with pytest.raises(ValueError, match="closed current"):
        current_root_parent_profile(version)
    with pytest.raises(ValueError, match="closed current"):
        current_issued_parent_profile(version)


def test_current_guard_revalidates_model_copy_instead_of_trusting_its_type() -> None:
    current = observation("262-1")
    bad = current.model_copy(update={"schema_version": "nexus.builder.parent-observation.v9"})
    with pytest.raises(ValueError):
        require_current_parent_profile(bad)
