"""Pure model/source fixture values; no source body, DB, model or credential operation."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from nexus.company.brain.source_models import BrainSource, BrainSourceHead
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.management.plan_catalog import NamedPlanResource, PlanAdmissionCatalog
from nexus.core.llm.company_registry import (
    EvaluationEvidence,
    ModelHealth,
    ModelRegistration,
    ModelRegistry,
    Profile,
)
from nexus.harness.standing_contracts import ToolPermission
from nexus.tests.unit.test_company_model_registry import model

if TYPE_CHECKING:
    from nexus.tests.unit.plan_admission_fixture_data import AdmissionFixture

COMPANY, WORKSPACE, OWNER = UUID(int=1), UUID(int=2), UUID(int=3)
NOW = datetime.now(UTC).replace(microsecond=0)


def _candidate(name: str, profile: Profile, seconds: int) -> ModelRegistration:
    return model(
        name,
        provider="test",
        api_family="test",
        price=None,
        health=ModelHealth(
            status="healthy",
            checked_at=NOW - timedelta(seconds=1),
            expires_at=NOW + timedelta(seconds=seconds),
        ),
        evaluations=(
            EvaluationEvidence(
                profile=profile,
                suite_version="mechanical",
                artifact_reference="fixture:not-live",
                score=Decimal(1),
                conformance_passed=True,
                evaluated_at=NOW - timedelta(seconds=1),
                expires_at=NOW + timedelta(seconds=seconds),
            ),
        ),
    )


def ordinary_catalog(
    resources: list[NamedPlanResource], tools: list[ToolPermission]
) -> PlanAdmissionCatalog:
    return PlanAdmissionCatalog(
        company_id=COMPANY,
        models=ModelRegistry(
            company_id=COMPANY,
            revision="catalog-v1",
            pricebook_version="fixture-prices",
            models=(
                _candidate("ordinary", "routine", 3600),
                _candidate("presentation", "engineering", 5),
            ),
        ),
        admitted_profiles=frozenset({"routine", "engineering"}),
        check_recipes=frozenset({"fixture.check.v1"}),
        resources=tuple(resources),
        tools=tuple(tools),
    )


def source_values() -> tuple[SourcePolicy, BrainSource, BrainSourceHead]:
    policy = SourcePolicy(
        source_symbol="fixture.window.v1",
        authority_profile="fixture-window",
        data_classification="internal",
        origin_kind="direct",
        media_type="text/plain",
        parser_version="utf8-identity-v1",
        chunker_version="utf8-sections-v1",
        search_config="simple",
        freshness_seconds=600,
        allowed_external_keys=frozenset({"raw"}),
    )
    source = BrainSource(
        company_id=COMPANY,
        source_id=UUID(int=5000),
        resource_id=UUID(int=2000),
        source_symbol=policy.source_symbol,
        external_key="raw",
        authority_profile=policy.authority_profile,
        data_classification="internal",
    )
    head = BrainSourceHead(
        company_id=COMPANY,
        source_id=source.source_id,
        current_revision_id=UUID(int=5001),
        generation=1,
        observed_at=NOW - timedelta(seconds=60),
        fresh_until=NOW + timedelta(seconds=540),
        availability="available",
    )
    return policy, source, head


def unused_charter_deadline(data: "AdmissionFixture") -> UUID:
    """Add a genuine typed unused declaration and an existing actor's finite resource grant."""
    # This >50-line fixture preserves exact current governance without registering new work.
    from nexus.company.brain.access_contracts import ResourceRef
    from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
    from nexus.company.contracts.company import DepartmentCharter
    from nexus.company.management.canonical import canonical_sha256
    from nexus.company.management.governance import CharterRevisionRef
    from nexus.company.management.governance_models import (
        ManagementCharterHead,
        ManagementCharterRevision,
    )

    key = UUID(int=9000)
    source = DepartmentCharter(
        company_id=COMPANY,
        department_id=UUID(int=9001),
        name="unused-declared",
        version="v1",
        responsibilities=("Unused ordinary declaration",),
        allowed_tools=("fixture.unused.read.v1",),
        resource_scopes=("fixture.unused",),
        deliverables=("No new work",),
        verifier_id=data.payload.children[1].binding.actor_id,
    )
    ref = CharterRevisionRef(
        company_id=COMPANY,
        department_id=source.department_id,
        revision_id=UUID(int=9002),
        version="v1",
        sha256=canonical_sha256(source),
    )
    data.objects[ManagementCharterHead, (COMPANY, ref.department_id)] = ManagementCharterHead(
        company_id=COMPANY,
        department_id=ref.department_id,
        current_revision_id=ref.revision_id,
        active=True,
    )
    data.objects[ManagementCharterRevision, (COMPANY, ref.revision_id)] = ManagementCharterRevision(
        company_id=COMPANY,
        revision_id=ref.revision_id,
        department_id=ref.department_id,
        version="v1",
        mandate_revision_id=data.payload.mandate.revision_id,
        sha256=ref.sha256,
        payload_json=source.model_dump_json(),
        recorded_by=OWNER,
        recorded_at=NOW,
    )
    data.objects[BrainResource, (COMPANY, key)] = BrainResource(
        company_id=COMPANY,
        resource_id=key,
        kind="artifact",
        active=True,
        acl_generation=1,
        created_at=NOW,
        updated_at=NOW,
    )
    principal = data.payload.children[0].binding.actor_id
    grant = BrainResourceAccess(
        company_id=COMPANY,
        resource_id=key,
        principal_id=principal,
        active=True,
        generation=1,
        expires_at=NOW + timedelta(seconds=5),
    )
    data.objects[BrainResourceAccess, (COMPANY, key, principal)] = grant
    data.grants.append(grant)
    data.payload = type(data.payload).model_validate(
        data.payload.model_dump() | {"charters": (*data.payload.charters, ref)}
    )
    data.catalog = PlanAdmissionCatalog.model_validate(
        data.catalog.model_dump()
        | {
            "resources": (
                *data.catalog.resources,
                NamedPlanResource(
                    symbol="fixture.unused",
                    resource=ResourceRef(company_id=COMPANY, resource_id=key),
                ),
            ),
            "tools": (
                *data.catalog.tools,
                ToolPermission(
                    tool="fixture.unused.read.v1", tool_version="v1", resource="fixture.unused"
                ),
            ),
        }
    )
    return key
