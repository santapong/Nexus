"""Exact Pydantic response serialization for the isolated company's runtime OpenAPI exports."""

import json
from copy import deepcopy
from typing import Any

from litestar import Request
from litestar.openapi.plugins import JsonRenderPlugin, YamlRenderPlugin
from pydantic import BaseModel

from nexus.api.company_management_control_routes import ManagementControlDescriptor
from nexus.company.access import PrincipalAccess
from nexus.company.management.action_review_contracts import ActionReview
from nexus.company.management.cancellation_contracts import OwnerCancellation
from nexus.company.management.commitment_contracts import CommitmentRevision
from nexus.company.management.goal_store import GoalRevisionRecord
from nexus.company.management.governance import CharterRevision, MandateRevision
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.metric_contracts import (
    MetricCurrentObservation,
    MetricObservationRecord,
)
from nexus.company.management.metric_query_contracts import MetricObservationPage
from nexus.company.management.native_profile_contracts import (
    NativeReportOperatingProfile,
    NativeReportPreparedAction,
)
from nexus.company.management.operating_report_contracts import SavedOperatingReport
from nexus.company.management.owner_view_contracts import (
    ApprovalPage,
    CompanyView,
    PlanView,
    TodayView,
    WorkView,
)
from nexus.company.notifications.inbox_contracts import (
    NotificationInboxEntry,
    NotificationInboxPage,
)
from nexus.company.pilot_session import PilotSessionToken
from nexus.execution.qualification_read_contracts import (
    QualificationDispatchRecord,
    QualificationRecipeView,
    QualificationResultView,
    QualificationStatus,
)
from nexus.execution.qualification_service import PreparedQualification

RESPONSE_MODELS: tuple[type[BaseModel], ...] = (
    PrincipalAccess,
    CompanyView,
    TodayView,
    PlanView,
    WorkView,
    ApprovalPage,
    CommitmentRevision,
    ActionReview,
    MandateRevision,
    CharterRevision,
    GoalRevisionRecord,
    PlanRevision,
    PilotSessionToken,
    ManagementControlDescriptor,
    OwnerCancellation,
    MetricCurrentObservation,
    MetricObservationRecord,
    MetricObservationPage,
    SavedOperatingReport,
    NativeReportOperatingProfile,
    NativeReportPreparedAction,
    NotificationInboxEntry,
    NotificationInboxPage,
    QualificationRecipeView,
    QualificationStatus,
    QualificationDispatchRecord,
    QualificationResultView,
    PreparedQualification,
)


def company_schema_document(document: dict[str, Any]) -> dict[str, Any]:
    """Keep actual routes; overlay only mounted response roots and their exact serialization defs.

    Any is limited to the framework's OpenAPI JSON boundary. No request or model
    payload is accepted here. Backend validation and source permissions are unchanged.
    """
    result = deepcopy(document)
    schemas = result.setdefault("components", {}).setdefault("schemas", {})
    for model in RESPONSE_MODELS:
        if model.__name__ not in schemas:
            continue
        exact = model.model_json_schema(
            mode="serialization", ref_template="#/components/schemas/{model}"
        )
        schemas.update(exact.pop("$defs", {}))
        schemas[model.__name__] = exact
    return result


class CompanyJsonRenderPlugin(JsonRenderPlugin):
    """Serve exact company response tuple/money shapes from the actual runtime route export."""

    def render(self, request: Request[Any, Any, Any], openapi_schema: dict[str, Any]) -> bytes:
        """Render actual routes and exact response definitions without mutating shared schema."""
        return super().render(request, company_schema_document(openapi_schema))


class CompanyYamlRenderPlugin(YamlRenderPlugin):
    """The YAML download describes the same response contract as the JSON download."""

    def render(self, request: Request[Any, Any, Any], openapi_schema: dict[str, Any]) -> bytes:
        """Render exact company response definitions into the pinned framework's YAML adapter."""
        # The framework's YAML adapter otherwise preserves Python tuple tags in
        # untouched route defaults. Normalize through the actual JSON encoder.
        portable = json.loads(self.render_json(request, company_schema_document(openapi_schema)))
        return super().render(request, portable)
