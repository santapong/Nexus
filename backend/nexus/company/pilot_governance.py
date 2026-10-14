"""Actual disposable mandate/charter/goal population preserves unknown business baseline."""

from decimal import Decimal
from uuid import uuid5

from nexus.company.brain.base import SourceTime
from nexus.company.contracts.company import CompanyMandate, DepartmentCharter
from nexus.company.management.base import RevisionRef
from nexus.company.management.control_support import charter_ref, mandate_ref
from nexus.company.management.goals import (
    DueIntent,
    GoalDefinition,
    GoalMetric,
    GoalRevisionRef,
    UnknownBaseline,
)
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.pilot_catalog import CHECK_TARGET, PUBLIC_SOURCE, REPORT_TARGET
from nexus.company.pilot_composition import PilotServices
from nexus.company.pilot_config import PilotConfig


def charter_definitions(config: PilotConfig) -> tuple[DepartmentCharter, ...]:
    author = DepartmentCharter(
        company_id=config.company_id,
        department_id=config.department_id,
        name="UAT report author",
        version="uat-author-v1",
        responsibilities=("Prepare synthetic UAT internal reports",),
        allowed_tools=("company.report.write.v1",),
        resource_scopes=(PUBLIC_SOURCE, REPORT_TARGET),
        deliverables=("Source-cited native UAT report",),
        verifier_id=config.verifier_id,
    )
    verifier = DepartmentCharter(
        company_id=config.company_id,
        department_id=uuid5(config.company_id, "uat-verification"),
        name="UAT report verifier",
        version="uat-verifier-v1",
        responsibilities=("Independently check UAT native reports",),
        allowed_tools=("company.report.check.v1",),
        resource_scopes=(PUBLIC_SOURCE, CHECK_TARGET),
        deliverables=("Mechanical protected check result",),
        verifier_id=config.owner_id,
    )
    return author, verifier


def goal_definition(config: PilotConfig, mandate: RevisionRef) -> GoalDefinition:
    return GoalDefinition(
        company_id=config.company_id,
        goal_id=config.goal_id,
        title="Verify disposable owner UAT report governance",
        owner_id=config.owner_id,
        mandate=mandate,
        metrics=(
            GoalMetric(
                company_id=config.company_id,
                metric_id="uat.accepted-native-reports",
                unit="count",
                comparator="ge",
                target=Decimal(1),
                baseline=UnknownBaseline(
                    reason="No independently accepted UAT report has been observed"
                ),
            ),
        ),
        due=DueIntent(
            source_time=SourceTime(
                precision="unknown",
                value=None,
                basis="No business deadline is supplied for this disposable UAT",
            )
        ),
    )


async def populate_governance(
    services: PilotServices, config: PilotConfig
) -> tuple[RevisionRef, tuple[CharterRevisionRef, ...], GoalRevisionRef]:
    mandate = await services.management.controls.publish_mandate(
        config.control(),
        config.identity(),
        CompanyMandate(
            company_id=config.company_id,
            owner_id=config.owner_id,
            version="uat-supervised-v1",
            purpose="Disposable supervised owner UAT; no live model or business completion claim",
            goals=(config.goal_id,),
            oversight="supervised",
        ),
        expected_revision_id=None,
    )
    charters = tuple(
        [
            await services.management.controls.publish_charter(
                config.control(),
                config.identity(),
                value,
                mandate=mandate_ref(mandate),
                expected_revision_id=None,
            )
            for value in charter_definitions(config)
        ]
    )
    goal = await services.management.goals.publish(
        config.control(),
        config.identity(),
        goal_definition(config, mandate_ref(mandate)),
        version="uat-goal-v1",
        expected_revision_id=None,
    )
    return (
        mandate_ref(mandate),
        tuple(charter_ref(row) for row in charters),
        GoalRevisionRef.model_validate_json(
            goal.model_dump_json(include=set(GoalRevisionRef.model_fields))
        ),
    )
