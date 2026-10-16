"""Real temporary Git/H/model files with supplied native/source SQL delivery.

These issued facts deliberately do NOT prove affordability, actual admission,
DBOS, RLS, live quality or runtime authority. The synthetic reviewed price may
reserve more than the synthetic C slice; only a coherent fresh actual profile
can qualify budget admission. Existing held allowances are never changed here.

Cohesion exception: this test-only actual H/TinyGit/model graph and its closed
supplied row delivery keep every source/native identifier in one reusable setup.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import Select
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.sql.dml import Insert

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import SourceRegistration
from nexus.company.management.coding_publication_contracts import (
    CodingPublicationRules,
    PublicationKind,
    publication_identity,
)
from nexus.tests.unit.test_coding_intent import prepared_case


def rules() -> CodingPublicationRules:
    prepared, catalog, _, _ = prepared_case()
    admission = catalog.nexus_coding_admission
    assert admission
    company, action = prepared.request.company_id, prepared.request.action_id
    registrations = []
    policies = []
    kinds: tuple[PublicationKind, ...] = ("model_origin", "code_patch")
    for index, kind in enumerate(kinds):
        source, _, _ = publication_identity(company, action, prepared.request_sha256, kind, b"x")
        symbol = "nexus.coding." + kind + ".v1"
        registrations.append(
            SourceRegistration(
                company_id=company,
                source_id=source.source_id,
                resource=ResourceRef(company_id=company, resource_id=UUID(int=800 + index)),
                source_symbol=symbol,
                external_key=str(action),
            )
        )
        policies.append(
            SourcePolicy(
                source_symbol=symbol,
                authority_profile="coding.generated.v1",
                data_classification="confidential",
                origin_kind="derived",
                media_type="application/json" if index == 0 else "text/plain",
                parser_version="utf8-identity-v1",
                chunker_version="utf8-sections-v1",
                search_config="simple",
                freshness_seconds=None,
                allowed_external_keys=frozenset({str(action)}),
                max_bytes=131072 if index == 0 else 32768,
            )
        )
    return CodingPublicationRules(
        company_id=company,
        action_id=action,
        origin=registrations[0],
        patch=registrations[1],
        origin_policy=policies[0],
        patch_policy=policies[1],
        readers=(admission.procedure.binding.actor_id,),
    )


async def graph(tmp_path: Path, *, real_repository: bool = False) -> SimpleNamespace:
    from nexus.company.access import CompanyControlScope
    from nexus.company.brain.blob_store import ProtectedBlobStore
    from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
    from nexus.company.management.coding_prepared_contracts import repository_selection
    from nexus.company.management.coding_prepared_store import CodingPreparedStore
    from nexus.company.management.coding_publication_store import CodingPublicationStore
    from nexus.company.management.coding_repository import CodingRepositoryReader
    from nexus.company.management.owner_view_sources import OwnerViewSources
    from nexus.company.management.plan_catalog import NamedPlanResource, PlanAdmissionCatalog
    from nexus.execution.planning_application_config import PlanningSourcePolicies
    from nexus.harness.model_evidence import FileModelEvidenceStore
    from nexus.tests.unit.nexus_report_fixture import credentials
    from nexus.tests.unit.test_coding_intent import runtime_graph

    repository_path = tmp_path
    if real_repository:
        from nexus.tests.unit.test_coding_prepared_store import repository_case

        prepared, catalog, _, lease, repository_path = repository_case(tmp_path)
    else:
        prepared, catalog, _, lease = prepared_case()
    value = rules()
    catalog = PlanAdmissionCatalog.model_validate_json(
        catalog.model_copy(
            update={
                "resources": (
                    *catalog.resources,
                    NamedPlanResource(symbol="coding.origin", resource=value.origin.resource),
                    NamedPlanResource(symbol="coding.patch", resource=value.patch.resource),
                )
            }
        ).model_dump_json()
    )
    factory, management, contexts = runtime_graph(tmp_path, prepared, catalog)
    assert type(management.freshness) is RegisteredSourceFreshness
    old = management.freshness._policies
    # Server composition before any H/J object is sealed, not a runtime graph replacement.
    management.freshness._policies = PlanningSourcePolicies(
        policies=(
            old.policy(prepared.sources[0].git.source_symbol),
            value.origin_policy,
            value.patch_policy,
        )
    )
    sources = OwnerViewSources(management.artifacts, management.freshness)
    repository = CodingRepositoryReader(repository_path, repository_selection(prepared))
    blobs = ProtectedBlobStore(tmp_path / "prepared", storage_symbol="coding-prepared-fixture")
    private = CodingPreparedStore(
        factory, management, contexts, blobs, sources, prepared.input_recipe, repository
    )
    evidence = FileModelEvidenceStore(tmp_path / "models")
    published = management.artifacts.blobs
    assert type(published) is ProtectedBlobStore
    publisher = CodingPublicationStore(
        factory, catalog, private, evidence, published, repository, rules=value
    )
    admission = catalog.nexus_coding_admission
    assert admission
    owner = await credentials(admission.procedure.binding).current(admission.procedure.binding)
    scope = CompanyControlScope(
        company_id=catalog.company_id,
        principal_id=owner.identity.principal_id,
        operation_id=UUID(int=903),
        trace_id=UUID(int=904),
    )
    return SimpleNamespace(
        prepared=prepared,
        catalog=catalog,
        private=private,
        model=evidence,
        publisher=publisher,
        owner=owner,
        scope=scope,
        rules=value,
        lease=lease,
    )


async def native_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Actual H/Git/model files; only current native/source SQL delivery is supplied."""
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal
    from uuid import uuid5

    from nexus.company.contracts.actions import ApprovalDecision
    from nexus.company.contracts.results import ActionReceipt
    from nexus.company.management.cycle_cost_contracts import (
        DirectoryCostWork,
        NativeCostAttempt,
        NativeCostHold,
        NativeCostSelection,
    )
    from nexus.company.management.plan_registration import registration
    from nexus.company.management.planning_native_facts import clock_us
    from nexus.core.llm.company_adapter_contracts import CompanyModelResult
    from nexus.core.llm.company_pricing import TokenUsage, quote_cost, reconcile_cost
    from nexus.execution.runtime_contracts import EffectRecord, ExecutionSnapshot
    from nexus.harness.canonical import action_hash
    from nexus.harness.journal_budget import billing_day
    from nexus.harness.journal_contracts import ActionRecord
    from nexus.harness.lifecycle import ActionState
    from nexus.harness.limits import LoopCounters
    from nexus.harness.model_evidence import ModelEvidence
    from nexus.tests.unit.test_coding_consumer import output
    from nexus.tests.unit.test_coding_intent import witness
    from nexus.tests.unit.test_coding_prepared_store import NativeDelivery

    value = await graph(tmp_path, real_repository=True)
    store, prepared = value.private, value.prepared
    delivery = NativeDelivery(store, prepared)
    delivery.install(monkeypatch)
    credential = await witness(prepared)
    ref = await store.save_worker(value.lease, credential, prepared, end_us=clock_us() + 20_000_000)
    delivery.publish(ref)
    model = next(
        row
        for row in value.catalog.models.models
        if row.registry_id == prepared.request.registry_id
    )
    now = datetime.now(UTC)
    native_at = now - timedelta(microseconds=1)
    quoted = quote_cost(model.price, prepared.request.bounds, now=now).amount_usd
    assert delivery.action is not None
    proposal = delivery.action.model_copy(update={"estimated_cost_usd": quoted})
    delivery.action = proposal
    digest = action_hash(proposal)
    saved = ModelEvidence(
        request=prepared.request,
        request_hash=prepared.request_sha256,
        action_hash=digest,
        model=model,
        registry_revision=prepared.request.registry_revision,
        price_version=prepared.request.price_version,
        recipe=prepared.input_recipe,
        input_estimate=prepared.input_estimate,
        result=CompanyModelResult(
            request_id=prepared.request.request_id,
            status="response",
            billing="known",
            usage=TokenUsage(input_tokens=10, output_tokens=100),
            structured_json=output(prepared),
        ),
        source_event_at=now,
        checked_at=now,
        owner_id=value.owner.identity.principal_id,
    )
    artifact = await value.model.save(saved)
    assert saved.result.usage is not None
    action = ActionRecord(
        company_id=proposal.company_id,
        proposal=proposal,
        proposal_hash=digest,
        approval=ApprovalDecision(
            company_id=proposal.company_id,
            decision_id=UUID(int=991),
            action_id=proposal.action_id,
            action_hash=digest,
            action_revision=1,
            approver_id=value.owner.identity.principal_id,
            decision="approved",
            issued_at=now - timedelta(seconds=10),
            expires_at=now + timedelta(seconds=60),
        ),
        state=ActionState.AUTHORIZED,
        consumed_at=native_at - timedelta(microseconds=1),
    )
    receipt = ActionReceipt(
        company_id=proposal.company_id,
        receipt_id=uuid5(proposal.action_id, "model-receipt-v1"),
        action_id=proposal.action_id,
        task_id=proposal.task_id,
        trace_id=proposal.trace_id,
        proposal_hash=digest,
        outcome="succeeded",
        recorded_at=now,
        artifacts=(artifact,),
    )
    admission = value.catalog.nexus_coding_admission
    slot = admission.slots[1]
    zero = LoopCounters(model_requests=0, tool_attempts=0, rework_rounds=0, plan_revisions=0)
    work = ExecutionSnapshot(
        company_id=proposal.company_id,
        registration=registration(slot.child.binding, slot.work, slot.child.quota),
        workspace_id=slot.child.binding.workspace_id,
        actor_id=proposal.actor_id,
        parent_task_id=admission.procedure.binding.task_id,
        state="verifying",
        counters=zero.model_copy(update={"model_requests": 1}),
        delegated=zero,
        fence=2,
        worker_id=None,
        lease_principal_id=None,
        expires_at=None,
        segment_number=1,
        segment_id=UUID(int=992),
        waiting_action_id=None,
    )
    native = NativeCostSelection(
        directory=DirectoryCostWork(
            company_id=proposal.company_id,
            task_id=proposal.task_id,
            trace_id=proposal.trace_id,
            actor_id=proposal.actor_id,
            workspace_id=work.workspace_id,
            parent_task_id=work.parent_task_id,
            root_task_id=admission.procedure.binding.task_id,
            allocation_usd=slot.child.allocation_usd,
            delegated_usd=Decimal(0),
            active=True,
            work=work,
        ),
        action=action,
        hold=NativeCostHold(
            company_id=proposal.company_id,
            action_id=proposal.action_id,
            task_id=proposal.task_id,
            day=billing_day(native_at),
            amount_usd=quoted,
            actual_usd=reconcile_cost(model.price, saved.result.usage, now=now).amount_usd,
            state="reconciled",
        ),
        intent=EffectRecord(
            company_id=proposal.company_id,
            action_id=proposal.action_id,
            task_id=proposal.task_id,
            trace_id=proposal.trace_id,
            run_id=work.registration.run_id,
            proposal_hash=digest,
            intent_fence=1,
            attempt_kind="model_requests",
            state="succeeded",
            created_at=native_at,
            receipt=receipt,
            verification=None,
        ),
        attempt=NativeCostAttempt(
            company_id=proposal.company_id,
            task_id=proposal.task_id,
            trace_id=proposal.trace_id,
            attempt_id=proposal.action_id,
            kind="model_requests",
            fence=1,
            reserved_at=native_at,
        ),
    )
    loaded = await store.load_owner(
        value.scope, value.owner, proposal.action_id, end_us=clock_us() + 20_000_000
    )
    value.delivery, value.native, value.saved, value.loaded, value.artifact = (
        delivery,
        native,
        saved,
        loaded,
        artifact,
    )
    return value


class SuppliedRows:
    """Closed in-memory SQL delivery, not an engine/transaction/RLS implementation."""

    def __init__(self) -> None:
        from unittest.mock import MagicMock

        from sqlalchemy.ext.asyncio import AsyncSession

        self.rows: list[object] = []
        self.inside = False
        self.entries = 0
        self.session = MagicMock(spec=AsyncSession)
        self.session.get = AsyncMock(side_effect=self.get)
        self.session.scalars = AsyncMock(side_effect=self.scalars)
        self.session.scalar = AsyncMock(side_effect=self.scalar)
        self.session.execute = AsyncMock(side_effect=self.execute)
        self.session.flush = AsyncMock()
        self.session.add.side_effect = self.add
        self.session.add_all.side_effect = self.add_all
        self.session.in_transaction.return_value = True

    def add(self, row: object) -> None:
        if all(row is not old for old in self.rows):
            self.rows.append(row)

    def add_all(self, rows: list[object]) -> None:
        for row in rows:
            self.add(row)

    async def get(self, entity: type[object], key: object) -> object | None:
        mapper = sqlalchemy_inspect(entity)
        assert mapper is not None
        names = tuple(column.key for column in mapper.primary_key)
        values = (
            tuple(key.get(name) for name in names)
            if isinstance(key, dict)
            else key
            if isinstance(key, tuple)
            else (key,)
        )
        return next(
            (
                row
                for row in self.rows
                if type(row) is entity and tuple(getattr(row, name) for name in names) == values
            ),
            None,
        )

    def selected(self, statement: Select[tuple[object, ...]], entity: type[object]) -> list[object]:
        import re
        from datetime import datetime

        parameters = statement.compile().params
        result = []
        for row in self.rows:
            if type(row) is not entity:
                continue
            valid = True
            for key, value in parameters.items():
                name = re.sub(r"_\d+$", "", key)
                if not hasattr(row, name) or isinstance(value, datetime):
                    continue
                actual = getattr(row, name)
                if actual not in value if isinstance(value, (tuple, list)) else actual != value:
                    valid = False
            if "active IS true" in str(statement) and row.__dict__.get("active") is False:
                valid = False
            if valid:
                result.append(row)
        return result

    async def scalars(self, statement: Select[tuple[object, ...]]) -> SimpleNamespace:
        descriptions = statement.column_descriptions
        entity, name = descriptions[0]["entity"], descriptions[0]["name"]
        rows = self.selected(statement, entity)
        result = rows if name == entity.__name__ else [getattr(row, name) for row in rows]
        return SimpleNamespace(all=lambda: result)

    async def scalar(self, statement: Select[tuple[object, ...]]) -> object:
        from datetime import UTC, datetime

        from nexus.company.brain.event_models import BrainEvent
        from nexus.company.brain.source_models import BrainSourceRevision

        text = str(statement)
        if "clock_timestamp()" in text:
            return datetime.now(UTC)
        if "max(" in text:
            return max(
                (row.sequence for row in self.rows if isinstance(row, BrainEvent)), default=0
            )
        if "EXISTS" in text:
            keys = [
                value
                for key, value in statement.compile().params.items()
                if key.startswith("artifact_revision_id")
            ]
            return any(
                isinstance(row, BrainSourceRevision) and row.artifact_revision_id in keys
                for row in self.rows
            )
        descriptions = statement.column_descriptions
        entity = descriptions[0]["entity"]
        rows = self.selected(statement, entity)
        return rows[0] if rows else None

    async def execute(self, statement: Select[tuple[object, ...]] | Insert) -> SimpleNamespace:
        from datetime import UTC, datetime

        from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
        from nexus.company.brain.event_models import BrainEvent

        if isinstance(statement, Insert):
            assert statement.table.name == BrainEvent.__tablename__
            self.add(BrainEvent(**statement.compile().params))
            return SimpleNamespace()
        descriptions = statement.column_descriptions
        entity = descriptions[0]["entity"]
        rows = self.selected(statement, entity)
        if len(descriptions) == 2 and entity is BrainResource:
            grants = self.selected(statement, BrainResourceAccess)
            now = datetime.now(UTC)
            pairs = [
                (resource, grant)
                for resource in rows
                for grant in grants
                if isinstance(resource, BrainResource)
                and isinstance(grant, BrainResourceAccess)
                and resource.resource_id == grant.resource_id
                and resource.active
                and grant.active
                and (grant.expires_at is None or grant.expires_at > now)
            ]
            return SimpleNamespace(all=lambda: pairs)
        mappings = [
            {description["name"]: getattr(row, description["name"]) for description in descriptions}
            for row in rows
        ]
        return SimpleNamespace(
            mappings=lambda: SimpleNamespace(one_or_none=lambda: mappings[0] if mappings else None)
        )


async def supplied_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Actual row writer/parser/Git/private IO; current native/source SQL is finite supplied data.

    Cohesion exception: this fixture and its tiny fixed SQL-row delivery keep actual
    protected H/model material bound to the exact same native IDs. No DB/API is run.
    """
    import copy
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from datetime import UTC, datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from nexus.company.brain.access_models import (
        BrainAccessEvent,
        BrainResource,
        BrainResourceAccess,
    )
    from nexus.company.brain.evidence_models import BrainEvidence
    from nexus.company.brain.source_models import (
        BrainArtifactRevision,
        BrainSource,
        BrainSourceHead,
        BrainSourceRevision,
    )
    from nexus.company.directory_models import DirectoryMembership
    from nexus.company.management import coding_publication_store as module
    from nexus.harness.journal_models import CompanyControl, JournalAction

    value = await native_files(tmp_path, monkeypatch)
    memory = SuppliedRows()
    prepared, owner = value.prepared, value.owner.identity.principal_id
    company = prepared.request.company_id
    control = value.delivery.control
    control.policy_version = value.native.action.proposal.policy_version
    control.price_version = prepared.request.price_version
    value.delivery.session = memory.session
    action = value.native.action
    memory.add(
        JournalAction(
            id=action.proposal.action_id,
            company_id=company,
            task_id=action.proposal.task_id,
            trace_id=action.proposal.trace_id,
            proposal_json=action.proposal.model_dump_json(by_alias=True),
            proposal_hash=action.proposal_hash,
            state=action.state.value,
            approval_json=action.approval.model_dump_json(),
            consumed_at=action.consumed_at,
        )
    )
    memory.add(
        DirectoryMembership(
            company_id=company,
            principal_id=owner,
            role="owner",
            principal_active=True,
            membership_active=True,
        )
    )
    now = datetime.now(UTC)
    heads = {row.source_id: row for row in prepared.context.manifest.source_heads}
    resources = [row.resource_id for row in prepared.context.manifest.contributors]
    from nexus.company.management.coding_sources import require_coding_sources

    originals = require_coding_sources(prepared.binding, prepared.context, prepared.sources)
    for index, code in enumerate(prepared.sources):
        resource = resources[index]
        policy = value.private.sources.freshness._policies.policy(code.git.source_symbol)
        memory.add(
            BrainSource(
                company_id=company,
                source_id=code.source.source_id,
                resource_id=resource,
                source_symbol=code.git.source_symbol,
                external_key=code.git.external_key,
                authority_profile=policy.authority_profile,
                data_classification=policy.data_classification,
                recorded_by=owner,
                recorded_at=now,
            )
        )
        memory.add(
            BrainArtifactRevision(
                company_id=company,
                **code.artifact.model_dump(exclude={"schema_version", "company_id"}),
                resource_id=resource,
                media_type="text/plain",
                storage_symbol=value.private.sources.artifacts.blobs.storage_symbol,
                raw_text=originals[code.file.path].decode(),
                derivation_id=None,
                data_classification=policy.data_classification,
                recorded_at=now,
            )
        )
        memory.add(
            BrainSourceRevision(
                company_id=company,
                source_id=code.source.source_id,
                source_revision_id=code.source.source_revision_id,
                revision=code.source.revision,
                artifact_revision_id=code.artifact.artifact_revision_id,
                derivation_id=None,
                source_event_precision=code.git.source_event.precision,
                source_event_value=code.git.source_event.value,
                source_event_basis=code.git.source_event.basis,
                source_author="actual temporary fixture commit",
                ingested_at=now,
                recorded_by=owner,
            )
        )
        head = heads[code.source.source_id]
        memory.add(
            BrainSourceHead(
                company_id=company,
                source_id=head.source_id,
                current_revision_id=head.current.source_revision_id,
                generation=head.generation,
                observed_at=head.observed_at,
                fresh_until=head.fresh_until,
                availability=head.availability,
            )
        )
    for inclusion in prepared.context.manifest.inclusions:
        record = inclusion.handle.record
        span = record.raw_span
        memory.add(
            BrainEvidence(
                company_id=company,
                evidence_id=record.evidence_id,
                source_id=record.source.source_id,
                source_revision_id=record.source.source_revision_id,
                artifact_revision_id=record.artifact.artifact_revision_id,
                raw_start_byte=span.start_byte,
                raw_end_byte=span.end_byte,
                raw_section=span.section,
                raw_path=span.path,
                raw_page=span.page,
                span_sha256=record.span_sha256,
                parse_revision_id=record.parse_revision_id,
                parsed_start_byte=span.start_byte,
                parsed_end_byte=span.end_byte,
                chunk_id=record.chunk_id,
            )
        )
    for registration, policy in (
        (value.rules.origin, value.rules.origin_policy),
        (value.rules.patch, value.rules.patch_policy),
    ):
        resource = registration.resource.resource_id
        resources.append(resource)
        memory.add(
            BrainSource(
                company_id=company,
                source_id=registration.source_id,
                resource_id=resource,
                source_symbol=registration.source_symbol,
                external_key=registration.external_key,
                authority_profile=policy.authority_profile,
                data_classification=policy.data_classification,
                recorded_by=owner,
                recorded_at=now,
            )
        )
        memory.add(
            BrainAccessEvent(
                company_id=company,
                event_id=UUID(int=9000 + len(resources)),
                resource_id=resource,
                principal_id=owner,
                generation=1,
                active=True,
                expires_at=None,
                owner_id=owner,
                operation_id=value.scope.operation_id,
                trace_id=value.scope.trace_id,
                recorded_at=now,
            )
        )
    for resource in resources:
        memory.add(
            BrainResource(
                company_id=company,
                resource_id=resource,
                kind="source",
                active=True,
                acl_generation=1,
                created_at=now,
                updated_at=now,
            )
        )
        memory.add(
            BrainResourceAccess(
                company_id=company,
                resource_id=resource,
                principal_id=owner,
                active=True,
                generation=1,
                expires_at=None,
            )
        )

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
        assert not memory.inside
        memory.inside = True
        memory.entries += 1
        before = copy.deepcopy(memory.rows)
        try:
            yield memory.session, control, datetime.now(UTC)
        except BaseException:
            memory.rows = before
            raise
        finally:
            memory.inside = False

    monkeypatch.setattr(module, "management_owner_transaction", transaction)
    monkeypatch.setattr(
        module, "native_cost_selection", AsyncMock(side_effect=lambda *_: value.native)
    )
    monkeypatch.setattr(module, "db_now", AsyncMock(side_effect=lambda _: datetime.now(UTC)))
    value.memory = memory
    value.control = control
    return value
