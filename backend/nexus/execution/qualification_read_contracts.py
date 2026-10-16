"""Safe owner-facing model-check descriptions, never provider or execution authority."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from nexus.company.contracts.base import USD
from nexus.company.management.goals import GoalRevisionRef
from nexus.core.llm.company_adapter_contracts import CompanyModelResult, JsonSchemaDocument
from nexus.core.llm.company_pricing import CostQuote, ModelContract
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.runtime_contracts import ExecutionSnapshot
from nexus.harness.journal_contracts import ActionRecord


class QualificationRecipeView(ModelContract):
    recipe_id: str
    recipe_sha256: str
    revision: str
    case_id: str
    goal: GoalRevisionRef
    provider: str
    model_id: str
    input_text: str
    system_text: str | None
    output_schema: JsonSchemaDocument | None
    request_output_cap: int
    maximum_reservation: CostQuote | None
    availability: Literal["current", "unavailable"]
    expires_at: datetime
    profile_quality_evaluated: Literal[False] = False


class QualificationHoldView(ModelContract):
    state: Literal["held", "unknown", "reconciled"]
    amount_usd: USD
    actual_usd: USD | None
    day: date


class QualificationDispatchRecord(ModelContract):
    command: SegmentCommand
    workflow_id: str
    disposition: Literal["enqueued", "existing"]


class QualificationEffectView(ModelContract):
    action_id: UUID
    state: str
    intent_fence: int
    created_at: datetime
    evidence_sha256s: tuple[str, ...]


class QualificationStatus(ModelContract):
    observed_at: datetime
    action: ActionRecord
    work: ExecutionSnapshot
    hold: QualificationHoldView | None
    recipe: QualificationRecipeView
    effect: QualificationEffectView | None
    dispatch: QualificationDispatchRecord | None
    company_completed: Literal[False] = False
    profile_quality_evaluated: Literal[False] = False


class QualificationResultView(ModelContract):
    availability: Literal["available", "unavailable"]
    provider_result: CompanyModelResult | None = None
    native_outcome: str | None = None
    captured_at: datetime | None = None
    sha256: str | None = None
    actual_usd: USD | None = None
    company_completed: Literal[False] = False
    profile_quality_evaluated: Literal[False] = False
