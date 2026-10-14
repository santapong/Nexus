"""Observed finite UAT-only TestModel qualification; no model client/tool activation."""

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.management.check_contracts import REPORT_CHECK_RECIPE
from nexus.company.management.plan_support import NamedPlanResource, PlanAdmissionCatalog
from nexus.company.pilot_config import PilotConfig
from nexus.core.llm.company_registry import (
    EvaluationEvidence,
    ModelHealth,
    ModelRegistration,
    ModelRegistry,
)
from nexus.harness.standing_contracts import ToolPermission

PUBLIC_SOURCE = "uat.source.public"
REPORT_TARGET = "uat.artifact.report"
CHECK_TARGET = "uat.artifact.check"


def offline_registration(config: PilotConfig) -> ModelRegistration:
    raw = config.sdk_receipt.read_bytes()
    receipt = json.loads(raw)
    if (
        receipt["model"] != "TestModel"
        or receipt["requests"] != 1
        or receipt["criteria_passed"] != receipt["criteria_total"]
    ):
        raise ValueError("Actual offline SDK qualification is unavailable")
    observed = datetime.fromisoformat(receipt["observed_at"])
    return ModelRegistration(
        registry_id="uat-only-testmodel-2.54",
        provider="test",
        model_id="test",
        endpoint_id="uat-local-only",
        api_family="test",
        enabled=True,
        capabilities=frozenset({"text"}),
        allowed_data=frozenset({"public", "internal", "confidential", "restricted"}),
        context_window=32768,
        max_output_tokens=2048,
        health=ModelHealth(
            status="healthy", checked_at=observed, expires_at=observed + timedelta(hours=4)
        ),
        evaluations=tuple(
            EvaluationEvidence(
                profile=profile,
                suite_version="uat-offline-sdk-one-request-v1",
                artifact_reference="sha256:" + hashlib.sha256(raw).hexdigest(),
                score=Decimal(receipt["score"]),
                conformance_passed=True,
                evaluated_at=observed,
                expires_at=observed + timedelta(hours=4),
            )
            for profile in ("routine", "verification")
        ),
    )


def pilot_catalog(config: PilotConfig) -> PlanAdmissionCatalog:
    registry = ModelRegistry(
        company_id=config.company_id,
        revision="uat-only-offline-v1",
        pricebook_version="uat-offline-v1",
        models=(offline_registration(config),),
    )
    return PlanAdmissionCatalog(
        company_id=config.company_id,
        models=registry,
        admitted_profiles=frozenset({"routine", "verification"}),
        check_recipes=frozenset({REPORT_CHECK_RECIPE}),
        tools=(
            ToolPermission(
                tool="company.report.write.v1", tool_version="v1", resource=REPORT_TARGET
            ),
            ToolPermission(
                tool="company.report.check.v1", tool_version="v1", resource=CHECK_TARGET
            ),
        ),
        resources=tuple(
            NamedPlanResource(
                symbol=symbol,
                resource=ResourceRef(company_id=config.company_id, resource_id=resource),
            )
            for symbol, resource in (
                (PUBLIC_SOURCE, config.public_resource_id),
                (REPORT_TARGET, config.report_resource_id),
                (CHECK_TARGET, config.check_resource_id),
            )
        ),
    )
