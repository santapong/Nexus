"""Management HTTP declarations; current signed-owner authority comes from server stores."""

from uuid import UUID

from pydantic import model_validator

from nexus.company.contracts.company import CompanyMandate, DepartmentCharter
from nexus.company.management.base import SHA256, Name, RevisionRef, ValueContract
from nexus.company.management.goals import GoalDefinition
from nexus.company.management.plans import PlanPayload

_INTEGER_KEYS = frozenset(
    {
        "revision",
        "generation",
        "expected_generation",
        "model_requests",
        "tool_attempts",
        "rework_rounds",
        "plan_revisions",
    }
)


def _literal_numbers(value: object) -> None:
    """Preserve wire numeric intent when HTTP decoders explicitly request non-strict mode."""
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str):
                if key in _INTEGER_KEYS and type(child) is not int:
                    raise ValueError("Revision and quota values require literal integers")
                if (key.endswith("_usd") or key == "value") and type(child) in {float, bool}:
                    raise ValueError("Money and metric values cannot be floats or booleans")
            _literal_numbers(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _literal_numbers(child)


class ManagementWire(ValueContract):
    @model_validator(mode="before")
    @classmethod
    def exact_numeric_intent(cls, value: object) -> object:
        _literal_numbers(value)
        return value


class MandatePublish(ManagementWire):
    mandate: CompanyMandate
    expected_revision_id: UUID | None


class CharterPublish(ManagementWire):
    charter: DepartmentCharter
    mandate: RevisionRef
    expected_revision_id: UUID | None


class GoalPublish(ManagementWire):
    definition: GoalDefinition
    version: Name
    expected_revision_id: UUID | None


class PlanPropose(ManagementWire):
    payload: PlanPayload
    expected_current_revision_id: UUID | None


class PlanDecision(ManagementWire):
    exact_hash: SHA256
    expected_current_revision_id: UUID | None
