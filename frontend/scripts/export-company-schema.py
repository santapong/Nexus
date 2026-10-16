"""Overlay exact Pydantic serialization schemas on the real Litestar route export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nexus.company.access import PrincipalAccess
from nexus.company.management.action_review_contracts import ActionReview
from nexus.company.management.api_contracts import PlanDecision
from nexus.company.management.commitment_contracts import CommitmentPublish, CommitmentRevision
from nexus.company.management.owner_view_contracts import (
    ApprovalPage,
    CompanyView,
    PlanView,
    TodayView,
    WorkView,
)
from nexus.company.pilot_session import PilotLogin, PilotSessionToken, PilotSignup
from nexus.execution.planning_owner_reads import PlanningInputReview
from nexus.execution.qualification_read_contracts import (
    QualificationDispatchRecord,
    QualificationRecipeView,
    QualificationResultView,
    QualificationStatus,
)
from nexus.execution.qualification_service import PreparedQualification


def export(source: Path, destination: Path) -> None:
    document = json.loads(source.read_text())
    schemas = document["components"]["schemas"]
    for model in (
        PrincipalAccess,
        CompanyView,
        TodayView,
        PlanView,
        WorkView,
        ApprovalPage,
        CommitmentRevision,
        CommitmentPublish,
        PlanDecision,
        ActionReview,
        PilotLogin,
        PilotSignup,
        PilotSessionToken,
        QualificationDispatchRecord,
        QualificationRecipeView,
        QualificationResultView,
        QualificationStatus,
        PreparedQualification,
        PlanningInputReview,
    ):
        # Optional model-check response definitions come from the concrete backend
        # models even when that service is unmounted. This adds no runtime route.
        exact = model.model_json_schema(
            mode="serialization", ref_template="#/components/schemas/{model}"
        )
        schemas.update(exact.pop("$defs", {}))
        schemas[model.__name__] = exact
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    export(arguments.source, arguments.destination)
