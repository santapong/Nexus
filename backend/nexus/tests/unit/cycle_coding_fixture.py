"""Real H Git/header/model files with supplied historical native and source SQL.

These historical charges do not assert valid original affordability: the held
synthetic C allocation remains unchanged. No native permission or SDK is issued.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid5

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.contracts.actions import ApprovalDecision
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management import coding_prepared_history as history
from nexus.company.management import cycle_coding_reader as coding_reader
from nexus.company.management import cycle_model_reader as finance
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_prepared_contracts import (
    encode_prepared,
    header_for,
    repository_selection,
)
from nexus.company.management.cycle_cost_contracts import (
    DirectoryCostWork,
    NativeCostAttempt,
    NativeCostHold,
    NativeCostSelection,
)
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.plan_registration import registration
from nexus.company.management.planning_native_facts import clock_us
from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
from nexus.core.llm.company_adapter_contracts import CompanyModelResult
from nexus.core.llm.company_endpoints import ServerEndpointBinding, SettingsEndpointResolver
from nexus.core.llm.company_pricing import TokenUsage, quote_cost, reconcile_cost
from nexus.execution.coding_services import CodingServices
from nexus.execution.runtime_contracts import EffectRecord, ExecutionSnapshot
from nexus.execution.runtime_support import registration_digest
from nexus.harness.canonical import action_hash
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_contracts import ActionRecord
from nexus.harness.lifecycle import ActionState
from nexus.harness.limits import LoopCounters
from nexus.harness.model_evidence import FileModelEvidenceStore, ModelEvidence
from nexus.harness.model_input_estimator import FullContextInputEstimator
from nexus.tests.unit.nexus_report_fixture import credentials
from nexus.tests.unit.test_coding_intent import Credential
from nexus.tests.unit.test_coding_prepared_store import saved_case
from nexus.tests.unit.test_nexus_coding_admission import planning_origin
from nexus.tests.unit.test_planning_application import application_settings


async def coding_case(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    status: Literal["response", "failed"] = "response",
) -> SimpleNamespace:
    store, prepared, lease, _, delivery = await saved_case(root, monkeypatch)
    catalog, now = store.management.catalog, datetime.now(UTC)
    admission = catalog.nexus_coding_admission
    assert admission is not None and delivery.action is not None
    owner = await credentials(admission.procedure.binding).current(admission.procedure.binding)
    scope = CompanyControlScope(
        company_id=catalog.company_id,
        principal_id=owner.identity.principal_id,
        operation_id=UUID(int=9200),
        trace_id=UUID(int=9201),
    )
    slot = admission.slots[1]
    registered = registration(slot.child.binding, slot.work, slot.child.quota)
    header = header_for(
        prepared,
        encode_prepared(prepared)[1],
        owner_id=owner.identity.principal_id,
        registration_sha256=registration_digest(registered),
        root_task_id=admission.procedure.binding.task_id,
        root_run_id=admission.procedure.binding.run_id,
        root_registration_sha256="c" * 64,
        procedure_id=admission.procedure.procedure_id,
    )
    from nexus.company.management.coding_prepared_contracts import header_reference

    reference, raw = header_reference(header)
    await store._io._save(reference.header, raw, clock_us() + 10_000_000)
    model = next(
        row for row in catalog.models.models if row.registry_id == prepared.request.registry_id
    )
    quote = quote_cost(model.price, prepared.request.bounds, now=now)
    # Supplied already-issued history records the exact original quotation. This
    # does not fund or mutate the declared C/root allocation or create an action.
    action = delivery.action.model_copy(update={"estimated_cost_usd": quote.amount_usd})
    digest = action_hash(action)
    usage = TokenUsage(input_tokens=100, output_tokens=20)
    evidence = ModelEvidence(
        request=prepared.request,
        request_hash=prepared.request_sha256,
        action_hash=digest,
        model=model,
        registry_revision=catalog.models.revision,
        price_version=catalog.models.pricebook_version,
        recipe=prepared.input_recipe,
        input_estimate=prepared.input_estimate,
        result=CompanyModelResult(
            request_id=prepared.request.request_id,
            status=status,
            billing="known",
            usage=usage,
            text="private generated result",
            structured_json='{"patch":"domain-invalid"}',
        ),
        source_event_at=now + timedelta(microseconds=100),
        checked_at=now + timedelta(microseconds=101),
        owner_id=owner.identity.principal_id,
    )
    model_root = root / "model"
    model_root.mkdir(mode=0o700)
    (model_root / str(catalog.company_id)).mkdir(mode=0o700)
    model_store = FileModelEvidenceStore(model_root)
    artifact = await model_store.save(evidence)
    receipt = ActionReceipt(
        company_id=catalog.company_id,
        receipt_id=uuid5(action.action_id, "model-receipt-v1"),
        action_id=action.action_id,
        task_id=action.task_id,
        trace_id=action.trace_id,
        proposal_hash=digest,
        outcome="succeeded" if status == "response" else "failed",
        recorded_at=evidence.checked_at,
        artifacts=(artifact,),
    )
    intent = EffectRecord(
        company_id=catalog.company_id,
        action_id=action.action_id,
        task_id=action.task_id,
        trace_id=action.trace_id,
        run_id=lease.run_id,
        proposal_hash=digest,
        attempt_kind="model_requests",
        intent_fence=1,
        state=receipt.outcome,
        receipt=receipt,
        verification=None,
        created_at=now,
    )
    work = ExecutionSnapshot(
        company_id=catalog.company_id,
        registration=registered,
        workspace_id=lease.workspace_id,
        actor_id=lease.actor_id,
        parent_task_id=admission.procedure.binding.task_id,
        state="verifying",
        counters=LoopCounters(model_requests=1, tool_attempts=0, rework_rounds=0, plan_revisions=0),
        delegated=LoopCounters(
            model_requests=0, tool_attempts=0, rework_rounds=0, plan_revisions=0
        ),
        fence=2,
        worker_id=None,
        lease_principal_id=None,
        expires_at=None,
        segment_number=1,
        segment_id=lease.segment_id,
        waiting_action_id=None,
    )
    selected = NativeCostSelection(
        directory=DirectoryCostWork(
            company_id=catalog.company_id,
            task_id=action.task_id,
            trace_id=action.trace_id,
            actor_id=action.actor_id,
            workspace_id=lease.workspace_id,
            parent_task_id=admission.procedure.binding.task_id,
            root_task_id=admission.procedure.binding.task_id,
            allocation_usd=slot.child.allocation_usd,
            delegated_usd=Decimal(0),
            active=False,
            work=work,
        ),
        action=ActionRecord(
            company_id=catalog.company_id,
            proposal=action,
            proposal_hash=digest,
            state=ActionState.AUTHORIZED,
            consumed_at=intent.created_at,
            approval=ApprovalDecision(
                company_id=catalog.company_id,
                decision_id=UUID(int=9202),
                action_id=action.action_id,
                action_revision=1,
                action_hash=digest,
                approver_id=owner.identity.principal_id,
                decision="approved",
                issued_at=now - timedelta(microseconds=1),
                expires_at=now + timedelta(microseconds=50),
            ),
        ),
        hold=NativeCostHold(
            company_id=catalog.company_id,
            action_id=action.action_id,
            task_id=action.task_id,
            day=billing_day(intent.created_at),
            amount_usd=quote.amount_usd,
            actual_usd=reconcile_cost(model.price, usage, now=evidence.source_event_at).amount_usd,
            state="reconciled",
        ),
        intent=intent,
        attempt=NativeCostAttempt(
            company_id=catalog.company_id,
            task_id=action.task_id,
            trace_id=action.trace_id,
            attempt_id=action.action_id,
            kind="model_requests",
            fence=1,
            reserved_at=intent.created_at,
        ),
    )
    payload = admission.payload("execution", origin=planning_origin(admission))
    assert canonical_sha256(payload) == header.plan.sha256
    row = ManagementPlanRevision(
        company_id=catalog.company_id,
        plan_id=header.plan.plan_id,
        plan_revision_id=header.plan.plan_revision_id,
        revision=header.plan.revision,
        sha256=header.plan.sha256,
        snapshot_json=payload.model_dump_json(),
        proposed_by=owner.identity.principal_id,
        recorded_at=now,
    )
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = row
    state = SimpleNamespace(
        selected=selected,
        revoked=False,
        signature="d" * 64,
        held=False,
        deadlines=(),
    )

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, object, None]]:
        assert not state.held, "nested CompanyControl transaction"
        state.held = True
        try:
            yield cast(AsyncSession, session), delivery.control, None
        finally:
            state.held = False

    async def native(*args: object, **kwargs: object) -> NativeCostSelection:
        return cast(NativeCostSelection, state.selected)

    async def sources(*args: object, **kwargs: object) -> tuple[str, tuple[datetime, ...]]:
        if state.revoked:
            raise BrainDeniedError("supplied current source revocation")
        return state.signature, state.deadlines

    monkeypatch.setattr(history, "management_owner_transaction", transaction)
    monkeypatch.setattr(finance, "management_owner_transaction", transaction)
    monkeypatch.setattr(coding_reader, "management_owner_transaction", transaction)
    monkeypatch.setattr(finance, "native_cost_selection", native)
    monkeypatch.setattr(finance, "stored_coding_profile", AsyncMock(return_value=True))
    monkeypatch.setattr(history, "root_registration", AsyncMock(return_value="c" * 64))
    monkeypatch.setattr(history, "action_sources", sources)
    monkeypatch.setattr(history, "require_code_metadata", AsyncMock())
    monkeypatch.setattr(history, "db_now", AsyncMock(side_effect=lambda _: datetime.now(UTC)))
    resolver = SettingsEndpointResolver(
        application_settings(),
        (
            ServerEndpointBinding(
                model.endpoint_id,
                model.provider,
                model.api_family,
                "https://generativelanguage.googleapis.com"
                if model.provider == "google"
                else "https://api.openai.com/v1",
            ),
        ),
    )
    services = CodingServices(
        factory=store.factory,
        management=store.management,
        contexts=store.contexts,
        prepared_blobs=store.blobs,
        source_views=store.sources,
        repository_path=store.repository._repository,
        repository_selection=repository_selection(prepared),
        code_sources=prepared.sources,
        estimator=FullContextInputEstimator(catalog.models, prepared.input_recipe),
        recipe=prepared.input_recipe,
        identities=NotificationWorkerIdentities(
            Credential(prepared),
            SecretStr("synthetic-coding-key-which-is-long-enough"),
            enabled=True,
        ),
        resolver=resolver,
        evidence=model_store,
        worker_id=lease.worker_id,
        registry_id=prepared.request.registry_id,
        max_output_tokens=prepared.request.bounds.max_output_tokens,
    )
    return SimpleNamespace(
        store=store,
        prepared=prepared,
        services=services,
        owner=owner,
        scope=scope,
        header=header,
        reference=reference,
        selected=selected,
        evidence=evidence,
        artifact=artifact,
        state=state,
        transaction=transaction,
        session=session,
        control=delivery.control,
    )
