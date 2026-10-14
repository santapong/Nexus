"""Unactivated method candidate; shared gate/spawn/result/cleanup algorithms remain unqualified."""

from typing import Literal

from nexus.builder.contained_contracts import ContainedValue, ObservationBounds
from nexus.builder.runtime_identity import RUNTIME_V2_METHOD_SHA256
from nexus.builder.user_parent_identity import USER_PARENT_METHOD_SHA256


class ExecutionMethodCandidate(ContainedValue):
    """A candidate description cannot provide the later full activation pin."""

    schema_version: Literal["nexus.builder.execution-method-candidate.v1"] = (
        "nexus.builder.execution-method-candidate.v1"
    )
    selector_sha256: str = RUNTIME_V2_METHOD_SHA256
    provider_sha256: str = USER_PARENT_METHOD_SHA256
    observer_version: Literal["nexus.builder.contained-observation.v1"] = (
        "nexus.builder.contained-observation.v1"
    )
    store_version: Literal["nexus.builder.containment-ref.v1"] = "nexus.builder.containment-ref.v1"
    bounds: ObservationBounds = ObservationBounds()
    execution_ready: Literal[False] = False


def execution_method_candidate() -> ExecutionMethodCandidate:
    """No full execution SHA is minted before shared algorithms and actual qualification exist."""
    return ExecutionMethodCandidate()
