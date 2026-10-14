"""A complete policy digest remains descriptive until exact trusted services qualify it."""

import pytest

from nexus.builder.contained_compiler import described_contained_script
from nexus.builder.policy import BuilderToolPolicy
from nexus.company.management.canonical import canonical_sha256
from nexus.tests.builder_support import described_policy
from nexus.tests.unit.test_contained_runtime_identity import configured


def test_absent_full_method_pin_preserves_default_policy_wire() -> None:
    policy = described_policy()
    assert policy.full_execution_method_sha256 is None
    assert "full_execution_method_sha256" not in policy.model_dump()


def test_v1_cannot_attach_a_full_contained_method_pin() -> None:
    with pytest.raises(ValueError, match="method"):
        BuilderToolPolicy.model_validate(
            described_policy().model_dump()
            | {
                "full_execution_method_sha256": "a" * 64,
            }
        )


def test_v2_full_method_pin_changes_exact_policy_but_never_activates_execution() -> None:
    spec, policy = configured()
    original = canonical_sha256(policy)
    policy = BuilderToolPolicy.model_validate(
        policy.model_dump()
        | {
            "full_execution_method_sha256": "a" * 64,
        }
    )
    spec = spec.model_copy(update={"policy_sha256": canonical_sha256(policy)})
    assert canonical_sha256(policy) != original
    assert described_contained_script(spec, policy).startswith("#!/bin/sh")
    with pytest.raises(ValueError, match="not configured"):
        spec.require_policy(policy)


@pytest.mark.parametrize("pin", [True, "bad", "A" * 64])
def test_malformed_full_pin_denies(pin: object) -> None:
    _, policy = configured()
    with pytest.raises(ValueError):
        BuilderToolPolicy.model_validate(
            policy.model_dump() | {"full_execution_method_sha256": pin}
        )
