"""Concrete synthetic C graph; native SQL/credential delivery never implies live authority."""

from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contained_query import clock_us
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.contracts.actions import ResourceRevision
from nexus.company.management.coding_consumer import RegisteredCodingConsumer
from nexus.company.management.coding_intent import PreparedCodingRequest
from nexus.company.management.coding_prepared_contracts import (
    StoredCodingRequest,
    encode_prepared,
    header_for,
    header_reference,
    repository_selection,
)
from nexus.company.management.coding_prepared_store import CodingPreparedStore
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.plan_registration import registration
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    NotificationWorkerIdentities,
)
from nexus.core.llm.company_adapter_contracts import EndpointResolver, ServerEndpoint
from nexus.execution.coding_services import CodingServices
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import registration_digest
from nexus.harness.model_authorizer_contracts import ModelInputRecipe
from nexus.harness.model_evidence import FileModelEvidenceStore
from nexus.harness.model_input_estimator import FullContextInputEstimator
from nexus.tests.unit.test_coding_intent import Credential, prepared_case, runtime_graph
from nexus.tests.unit.test_company_provider_conformance import (
    EndpointResolver as SuppliedEndpointResolver,
)


def runtime_case(root: Path) -> tuple[CodingServices, PreparedCodingRequest, ExecutionLease]:
    prepared, catalog, estimator, lease = prepared_case()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ("brain", "prepared", "model"):
        directory = root / name
        directory.mkdir(mode=0o700, exist_ok=True)
        (directory / str(catalog.company_id)).mkdir(mode=0o700, exist_ok=True)
        assert not directory.stat().st_mode & 0o077
        assert not (directory / str(catalog.company_id)).stat().st_mode & 0o077
    factory, management, contexts = runtime_graph(root, prepared, catalog)
    row = next(
        row for row in catalog.models.models if row.registry_id == prepared.request.registry_id
    )
    endpoint = ServerEndpoint(
        endpoint_id=row.endpoint_id,
        provider=row.provider,
        api_family=row.api_family,
        base_url="https://offline.invalid/v1",
        api_key=SecretStr("synthetic-no-vendor-key"),
        timeout_seconds=1,
        transport=httpx2.MockTransport(lambda _: httpx2.Response(500)),
    )
    configured = CodingServices(
        factory=factory,
        management=management,
        contexts=contexts,
        prepared_blobs=ProtectedBlobStore(root / "prepared", storage_symbol="coding:prepared"),
        source_views=OwnerViewSources(management.artifacts, management.freshness),
        repository_path=root.resolve(),
        repository_selection=repository_selection(prepared),
        code_sources=prepared.sources,
        estimator=estimator,
        recipe=prepared.input_recipe,
        identities=NotificationWorkerIdentities(
            Credential(prepared),
            SecretStr("synthetic-coding-key-which-is-long-enough"),
            enabled=True,
        ),
        resolver=SuppliedEndpointResolver(endpoint),
        evidence=FileModelEvidenceStore(root / "model"),
        worker_id=lease.worker_id,
        registry_id=row.registry_id,
        max_output_tokens=512,
    )
    return configured, prepared, lease


def command(prepared: PreparedCodingRequest, lease: ExecutionLease) -> SegmentCommand:
    call = prepared.request
    return SegmentCommand(
        company_id=call.company_id,
        task_id=call.task_id,
        trace_id=call.trace_id,
        actor_id=call.actor_id,
        workspace_id=lease.workspace_id,
        run_id=lease.run_id,
        action_id=call.action_id,
        segment_id=lease.segment_id,
    )


def native_work(value: CodingServices, lease: ExecutionLease) -> ExecutionWork:
    """Complete supplied native row, not an actual registered company fact."""
    admission = value.management.catalog.nexus_coding_admission
    assert admission is not None
    slot = admission.slots[1]
    bound = slot.child.binding
    actual = registration(bound, slot.work, slot.child.quota)
    counters = {
        f"{kind}_{suffix}": getattr(slot.child.quota, kind) if suffix == "limit" else 0
        for kind in ("model_requests", "tool_attempts", "rework_rounds", "plan_revisions")
        for suffix in ("limit", "used", "delegated")
    }
    return ExecutionWork(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        workspace_id=bound.workspace_id,
        run_id=bound.run_id,
        parent_task_id=admission.procedure.binding.task_id,
        registration_json=actual.model_dump_json(),
        registration_hash=registration_digest(actual),
        workflow_name=bound.workflow_name,
        workflow_version=bound.workflow_version,
        model_profile=bound.model_profile,
        model_registry_version=bound.model_registry_version,
        state="running",
        fence=lease.fence,
        worker_id=lease.worker_id,
        lease_principal_id=bound.actor_id,
        lease_mode="execute",
        lease_until=lease.expires_at,
        segment_id=lease.segment_id,
        segment_number=1,
        **counters,
    )


def description(value: CodingServices, prepared: PreparedCodingRequest) -> StoredCodingRequest:
    """Metadata only; this directly constructed value is deliberately NOT store-issued proof."""
    admission = value.management.catalog.nexus_coding_admission
    assert admission is not None
    _, body = encode_prepared(prepared)
    header = header_for(
        prepared,
        body,
        owner_id=admission.procedure.binding.actor_id,
        registration_sha256="a" * 64,
        root_task_id=admission.procedure.binding.task_id,
        root_run_id=admission.procedure.binding.run_id,
        root_registration_sha256="b" * 64,
        procedure_id=admission.procedure.procedure_id,
    )
    reference, _ = header_reference(header)
    return StoredCodingRequest(prepared, reference, header, clock_us() + 20_000_000)


def bind_real_consumer_delivery(monkeypatch: pytest.MonkeyPatch) -> list[RegisteredCodingConsumer]:
    """Only native claim/record/release leaves supplied; retain real consumer+SDK+protected IO."""
    from nexus.execution import coding_worker as worker
    from nexus.tests.unit.test_coding_consumer import install_native_delivery

    seen = []

    def build(
        factory: async_sessionmaker[AsyncSession],
        management: ManagementExecutionServices,
        contexts: PersistentContextAssembler,
        evidence: FileModelEvidenceStore,
        resolver: EndpointResolver,
        estimator: FullContextInputEstimator,
        recipe: ModelInputRecipe,
        lease: ExecutionLease,
        credential: AuthenticatedWorkerIdentity,
        *,
        resources: tuple[ResourceRevision, ...],
        prepared_store: CodingPreparedStore,
        stored: StoredCodingRequest,
        end_us: int,
        sdk_end_us: int,
    ) -> RegisteredCodingConsumer:
        actual = RegisteredCodingConsumer(
            factory,
            management,
            contexts,
            evidence,
            resolver,
            estimator,
            recipe,
            lease,
            credential,
            resources=resources,
            prepared_store=prepared_store,
            stored=stored,
            end_us=end_us,
            sdk_end_us=sdk_end_us,
        )
        install_native_delivery(actual, monkeypatch)
        seen.append(actual)
        return actual

    monkeypatch.setattr(worker, "RegisteredCodingConsumer", build)
    return seen


def services_from_store(
    root: Path,
    store: CodingPreparedStore,
    prepared: PreparedCodingRequest,
    lease: ExecutionLease,
    transport: httpx2.AsyncBaseTransport,
    *,
    endpoint_timeout_seconds: float = 1,
) -> CodingServices:
    """Reuse the actual H graph and roots; no copied/fake private proof."""
    row = next(
        row
        for row in store.management.catalog.models.models
        if row.registry_id == prepared.request.registry_id
    )
    endpoint = ServerEndpoint(
        endpoint_id=row.endpoint_id,
        provider=row.provider,
        api_family=row.api_family,
        base_url="https://offline.invalid/v1",
        api_key=SecretStr("synthetic-no-vendor-key"),
        timeout_seconds=endpoint_timeout_seconds,
        transport=transport,
    )
    directory = root / "model"
    directory.mkdir(mode=0o700, exist_ok=True)
    (directory / str(prepared.request.company_id)).mkdir(mode=0o700, exist_ok=True)
    return CodingServices(
        factory=store.factory,
        management=store.management,
        contexts=store.contexts,
        prepared_blobs=store.blobs,
        source_views=store.sources,
        repository_path=(root / "repository").resolve(),
        repository_selection=repository_selection(prepared),
        code_sources=prepared.sources,
        estimator=FullContextInputEstimator(store.management.catalog.models, prepared.input_recipe),
        recipe=prepared.input_recipe,
        identities=NotificationWorkerIdentities(
            Credential(prepared),
            SecretStr("synthetic-coding-key-which-is-long-enough"),
            enabled=True,
        ),
        resolver=SuppliedEndpointResolver(endpoint),
        evidence=FileModelEvidenceStore(directory),
        worker_id=lease.worker_id,
        registry_id=row.registry_id,
        max_output_tokens=512,
    )
