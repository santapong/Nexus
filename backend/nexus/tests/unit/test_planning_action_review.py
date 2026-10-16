"""Actual protected input and review orchestration; native/SQL delivery is supplied."""

# Cohesion exception: one shared actual-file fixture and its closure/legacy
# controls stay together; none of the supplied native delivery qualifies SQL.

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import BrainReadScope
from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.company.contracts.company import DepartmentCharter
from nexus.company.management import action_review_planning as planning_checks
from nexus.company.management import action_review_resources as resources
from nexus.company.management import action_review_store as module
from nexus.company.management import planning_prepared_store as protected
from nexus.company.management.action_review_store import OwnerActionReviewStore
from nexus.company.management.base import RevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.governance import CharterRevision
from nexus.company.management.governance_models import ManagementCharterRevision
from nexus.company.management.owner_view_sources import SourceDisclosure
from nexus.company.management.plan_catalog import NamedPlanResource, PlanAdmissionCatalog
from nexus.company.management.plan_registration import registration
from nexus.company.management.planning_native_facts import clock_us
from nexus.company.management.planning_prepared_contracts import StoredPlanningRequest
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import registration_digest
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.tests.unit import test_planning_owner_reads as inputs
from nexus.tests.unit.test_company_brain_context_render import material
from nexus.tests.unit.test_company_planning_consumer import planning_registry
from nexus.tests.unit.test_planning_prepared_store import Fixture
from nexus.tests.unit.test_planning_prepared_store import setup as base_setup

STATIC_RESOURCE = UUID(int=10001)


async def review_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, extra_static: bool = False
) -> tuple[Fixture, OwnerActionReviewStore]:
    """Keep real protected persistence; no fabricated authorization or live SQL claim."""
    original = base_setup

    def configured(path: Path, patch: pytest.MonkeyPatch) -> Fixture:
        f = original(path, patch)
        binding = f.current.child.binding.model_copy(
            update={"workflow_name": "company.planning.v1", "workflow_version": "v1"}
        )
        child = f.current.child.model_copy(update={"binding": binding})
        native = cast(ExecutionWork, f.rows[ExecutionWork])
        record = registration(binding, f.current.work, child.quota)
        native.workflow_name = binding.workflow_name
        native.workflow_version = binding.workflow_version
        native.registration_json = record.model_dump_json()
        native.registration_hash = registration_digest(record)
        f.current = f.current.model_copy(
            update={"child": child, "work_sha256": native.registration_hash}
        )
        return f

    monkeypatch.setattr(inputs, "setup", configured)
    original_registry = planning_registry

    def eligible(provider: str) -> ModelRegistry:
        # Synthetic eligibility dates are fixture data, never live model qualification.
        registry = original_registry(provider)
        now = datetime.now(UTC)
        model = registry.models[0]
        return registry.model_copy(
            update={
                "models": (
                    model.model_copy(
                        update={
                            "evaluations": tuple(
                                row.model_copy(
                                    update={
                                        "evaluated_at": now - timedelta(minutes=1),
                                        "expires_at": now + timedelta(hours=1),
                                    }
                                )
                                for row in model.evaluations
                            ),
                        }
                    ),
                )
            }
        )

    monkeypatch.setattr(inputs, "planning_registry", eligible)
    f, reader = await inputs.case(tmp_path, monkeypatch)
    call = f.prepared.request
    target = f"model:{call.registry_id}"
    resource = ResourceRef(
        company_id=call.company_id,
        resource_id=f.prepared.context.manifest.contributors[0].resource_id,
    )
    catalog = PlanAdmissionCatalog(
        company_id=call.company_id,
        models=reader.registry,
        admitted_profiles=frozenset({f.prepared.input_recipe.profile}),
        check_recipes=frozenset(),
        resources=tuple(
            NamedPlanResource(symbol=value, resource=resource) for value in (target, "knowledge")
        )
        + (
            (
                NamedPlanResource(
                    symbol="charter.extra",
                    resource=ResourceRef(company_id=call.company_id, resource_id=STATIC_RESOURCE),
                ),
            )
            if extra_static
            else ()
        ),
    )
    charter = DepartmentCharter(
        company_id=call.company_id,
        department_id=f.current.child.charter.department_id,
        name="Planning",
        version=f.current.child.charter.version,
        responsibilities=("Produce an owner-reviewed Nexus plan",),
        allowed_tools=("model.request.v1",),
        resource_scopes=(target, "knowledge") + (("charter.extra",) if extra_static else ()),
        deliverables=("Reviewable plan",),
        verifier_id=f.owner.principal_id,
    )
    reference = f.current.child.charter.model_copy(update={"sha256": canonical_sha256(charter)})
    f.current = f.current.model_copy(
        update={"child": f.current.child.model_copy(update={"charter": reference})}
    )
    actual = CharterRevision(
        **reference.model_dump(),
        charter=charter,
        mandate=RevisionRef.model_validate(
            reference.model_dump(include={"company_id", "revision_id", "version", "sha256"})
        ),
        recorded_by=f.owner.principal_id,
        recorded_at=datetime.now(UTC),
    )
    f.rows[ManagementCharterRevision] = ManagementCharterRevision()
    monkeypatch.setattr(resources, "charter_record", AsyncMock(return_value=actual))
    artifact = material().record.artifact
    extra = artifact.model_copy(
        update={
            "artifact_id": UUID(int=10002),
            "artifact_revision_id": UUID(int=10003),
        }
    )
    monkeypatch.setattr(
        resources,
        "current_artifact",
        AsyncMock(
            side_effect=(
                lambda session, resource_id, binding, *, empty_target=False: (
                    extra if resource_id == STATIC_RESOURCE else artifact
                )
            )
        ),
    )
    monkeypatch.setattr(resources, "db_clock", AsyncMock(side_effect=lambda _: datetime.now(UTC)))
    monkeypatch.setattr(module, "db_clock", AsyncMock(side_effect=lambda _: datetime.now(UTC)))
    monkeypatch.setattr(
        planning_checks, "db_clock", AsyncMock(side_effect=lambda _: datetime.now(UTC))
    )
    monkeypatch.setattr(module, "require_member", AsyncMock())
    monkeypatch.setattr(module, "require_current_governance", AsyncMock())
    monkeypatch.setattr(module, "source_disclosure", AsyncMock(return_value=SourceDisclosure(None)))
    monkeypatch.setattr(module, "require_resources", AsyncMock(return_value=()))
    active = False

    @asynccontextmanager
    async def transaction(
        factory: async_sessionmaker[AsyncSession],
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        *,
        allow_paused: bool = False,
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
        nonlocal active
        assert not active and factory is f.store.factory and identity == f.owner
        active = True
        try:
            yield f.session, cast(CompanyControl, f.rows[CompanyControl]), datetime.now(UTC)
        finally:
            active = False

    @asynccontextmanager
    async def brain(
        factory: async_sessionmaker[AsyncSession],
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        *,
        owner: bool = False,
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
        assert not active, "load_owner must never nest the CompanyControl mutex"
        assert factory is f.store.factory and scope.principal_id == identity.principal_id
        assert identity == f.owner if owner else identity.principal_id == f.lease.actor_id
        yield f.session, cast(CompanyControl, f.rows[CompanyControl]), datetime.now(UTC)

    monkeypatch.setattr(module, "management_owner_transaction", transaction)
    monkeypatch.setattr(protected, "brain_transaction", brain)
    reviews = OwnerActionReviewStore(f.store.factory, catalog, f.store.sources, planning=f.store)
    return f, reviews


async def test_current_prepared_planning_action_is_reviewable_without_catalog_marker_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f, reviews = await review_case(tmp_path, monkeypatch)
    result = await reviews.review(f.scope, f.owner, f.prepared.request.action_id)
    assert result.availability == "available" and result.detail is not None
    assert result.detail.proposal_sha256 == result.audit.proposal_sha256
    assert f.prepared.request.input_text not in result.model_dump_json()
    assert not f.store.pending_owners()


async def test_unconfigured_planning_stays_unavailable_with_safe_native_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f, configured = await review_case(tmp_path, monkeypatch)
    reviews = OwnerActionReviewStore(f.store.factory, configured.catalog, f.store.sources)
    result = await reviews.review(f.scope, f.owner, f.prepared.request.action_id)
    assert result.availability == "unavailable" and result.detail is None
    assert result.audit.action_id == f.prepared.request.action_id


async def test_original_model_action_gate_denies_before_private_file_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f, reviews = await review_case(tmp_path, monkeypatch)
    gate = MagicMock(side_effect=ValueError("actual managed model eligibility denied"))
    monkeypatch.setattr(resources, "validate_plan_action", gate)
    read = AsyncMock(side_effect=AssertionError("private bytes must not be read"))
    monkeypatch.setattr(f.store.blobs, "read", read)
    result = await reviews.review(f.scope, f.owner, f.prepared.request.action_id)
    assert result.detail is None and gate.call_count == 1
    read.assert_not_called()


@pytest.mark.parametrize("change", ("extra", "missing", "crossed", "hash", "parameter"))
async def test_complete_dynamic_conditions_and_request_hash_are_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    f, reviews = await review_case(tmp_path, monkeypatch)
    row = cast(JournalAction, f.rows[JournalAction])
    proposal = ActionProposal.model_validate_json(row.proposal_json)
    conditions = proposal.preconditions
    if change == "extra":
        conditions += (ResourceRevision(resource="untrusted:extra", revision="v1"),)
    elif change == "missing":
        conditions = conditions[1:]
    elif change == "crossed":
        conditions = (conditions[0].model_copy(update={"revision": "acl:999"}), *conditions[1:])
    changed = proposal.model_copy(update={"preconditions": conditions})
    if change == "parameter":
        changed = changed.model_copy(update={"parameters": changed.parameters | {"extra": True}})
    row.proposal_json = changed.model_dump_json()
    row.proposal_hash = "f" * 64 if change == "hash" else action_hash(changed)
    if change == "hash":
        with pytest.raises(ValueError, match="audit differs"):
            await reviews.review(f.scope, f.owner, proposal.action_id)
        return
    result = await reviews.review(f.scope, f.owner, proposal.action_id)
    assert result.detail is None and result.availability == "unavailable"
    assert f.prepared.request.input_text not in result.model_dump_json()


@pytest.mark.parametrize("change", ("source", "goal", "head", "charter"))
async def test_actual_post_body_source_native_changes_prevent_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    from nexus.company.brain.sources import ArtifactRevisionRef
    from nexus.company.management.governance_models import ManagementGoalHead
    from nexus.company.management.plan_models import ManagementPlanHead

    f, reviews = await review_case(tmp_path, monkeypatch)
    original = f.store.blobs.read

    async def changed(ref: ArtifactRevisionRef) -> bytes:
        raw = await original(ref)
        if ref.revision == "planning-prepared-body-v1":
            if change == "source":
                f.revoked = True
            elif change == "goal":
                cast(ManagementGoalHead, f.rows[ManagementGoalHead]).active = False
            elif change == "head":
                cast(ManagementPlanHead, f.rows[ManagementPlanHead]).current_revision_id = UUID(
                    int=999
                )
            else:
                f.current = f.current.model_copy(
                    update={
                        "child": f.current.child.model_copy(
                            update={
                                "charter": f.current.child.charter.model_copy(
                                    update={"sha256": "f" * 64}
                                )
                            }
                        )
                    }
                )
        return raw

    monkeypatch.setattr(f.store.blobs, "read", changed)
    result = await reviews.review(f.scope, f.owner, f.prepared.request.action_id)
    assert result.detail is None
    assert not f.store.pending_owners()


async def test_loaded_source_cutoff_is_not_reset_by_final_metadata_awaits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f, reviews = await review_case(tmp_path, monkeypatch)
    original = f.store.load_owner

    async def load(
        scope: CompanyControlScope, identity: VerifiedIdentity, action_id: UUID, *, end_us: int
    ) -> StoredPlanningRequest:
        actual = await original(scope, identity, action_id, end_us=end_us)
        return replace(actual, read_end_us=clock_us() + 20_000)

    async def late(*args: object) -> None:
        await asyncio.sleep(0.04)

    monkeypatch.setattr(f.store, "load_owner", load)
    monkeypatch.setattr(module, "_final_review_reads", late)
    with pytest.raises(TimeoutError):
        await reviews.read(
            f.scope, f.owner, f.prepared.request.action_id, end_us=clock_us() + 30_000_000
        )


async def test_concrete_factory_and_original_catalog_cannot_be_swapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f, reviews = await review_case(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="same-factory"):
        OwnerActionReviewStore(
            async_sessionmaker(), reviews.catalog, f.store.sources, planning=f.store
        )
    reviews.catalog = reviews.catalog.model_copy(
        update={
            "models": reviews.catalog.models.model_copy(
                update={
                    "models": (
                        reviews.catalog.models.models[0].model_copy(update={"model_id": "crossed"}),
                    )
                }
            )
        }
    )
    with pytest.raises(ValueError, match="composition"):
        await reviews.review(f.scope, f.owner, f.prepared.request.action_id)


async def test_legacy_fixed_symbol_review_needs_no_planning_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.harness.standing_contracts import ToolPermission

    f, configured = await review_case(tmp_path, monkeypatch)
    work = cast(ExecutionWork, f.rows[ExecutionWork])
    work.workflow_name = "fixture.internal"
    charter = DepartmentCharter(
        company_id=f.scope.company_id,
        department_id=f.current.child.charter.department_id,
        name="Legacy internal read",
        version="v1",
        responsibilities=("Read the fixed source",),
        allowed_tools=("fake.internal.read.v1",),
        resource_scopes=("knowledge",),
        deliverables=("Exact review",),
        verifier_id=f.owner.principal_id,
    )
    reference = f.current.child.charter.model_copy(update={"sha256": canonical_sha256(charter)})
    monkeypatch.setattr(
        resources,
        "charter_record",
        AsyncMock(
            return_value=CharterRevision(
                **reference.model_dump(),
                charter=charter,
                mandate=RevisionRef.model_validate(
                    reference.model_dump(include={"company_id", "revision_id", "version", "sha256"})
                ),
                recorded_by=f.owner.principal_id,
                recorded_at=datetime.now(UTC),
            )
        ),
    )
    row = cast(JournalAction, f.rows[JournalAction])
    proposal = ActionProposal.model_validate_json(row.proposal_json).model_copy(
        update={
            "tool": "fake.internal.read.v1",
            "resource": "knowledge",
            "parameters": {"note": "LEGACY_EXACT_ARGUMENT"},
            "preconditions": (),
        }
    )
    row.proposal_json, row.proposal_hash = proposal.model_dump_json(), action_hash(proposal)
    catalog = configured.catalog.model_copy(
        update={
            "tools": (ToolPermission(tool=proposal.tool, tool_version="v1", resource="knowledge"),)
        }
    )
    reviews = OwnerActionReviewStore(f.store.factory, catalog, f.store.sources)
    result = await reviews.review(f.scope, f.owner, proposal.action_id)
    assert result.availability == "available" and result.detail is not None
    assert result.detail.proposal.parameters == {"note": "LEGACY_EXACT_ARGUMENT"}


async def test_same_registry_version_cannot_relabel_saved_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f, configured = await review_case(tmp_path, monkeypatch)
    registry = configured.catalog.models
    crossed = registry.model_copy(
        update={"models": (registry.models[0].model_copy(update={"model_id": "crossed-model"}),)}
    )
    reviews = OwnerActionReviewStore(
        f.store.factory,
        configured.catalog.model_copy(update={"models": crossed}),
        f.store.sources,
        planning=f.store,
    )
    result = await reviews.review(f.scope, f.owner, f.prepared.request.action_id)
    assert result.availability == "unavailable" and result.detail is None
