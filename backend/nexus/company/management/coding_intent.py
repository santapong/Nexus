"""Complete reviewed C input and concrete current native/context intent predicates."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Self

from pydantic import model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.base import SHA256, BrainReadScope, ValueContract
from nexus.company.brain.context import AssembledContext
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.model_context_check import BrainModelContextCheck
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_content import CodingBinding, coding_schema
from nexus.company.management.coding_sources import CodingSourceRef, require_coding_sources
from nexus.company.management.governance_models import ManagementGoalHead, ManagementGoalRevision
from nexus.company.management.nexus_coding_admission import NexusCodingAdmission
from nexus.company.management.nexus_coding_catalog import (
    configured_nexus_admission,
    select_configured_nexus_plan,
)
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.planning_authority import ManagementPlanningAuthority
from nexus.company.management.revision_store import plan_record, plan_reference
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest, request_hash
from nexus.core.llm.company_registry import ModelRegistration, ModelRegistry
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.model_authorizer_contracts import (
    InputEstimate,
    ModelInputRecipe,
    model_action_parameters,
    require_input_estimate,
)
from nexus.harness.model_input_estimator import FullContextInputEstimator


def coding_parameters_sha256(call: CompanyModelRequest, recipe: ModelInputRecipe) -> str:
    """Fingerprint the exact existing nine native parameters, without changing their wire."""
    return hashlib.sha256(
        json.dumps(
            model_action_parameters(call, recipe),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


class PreparedCodingRequest(ValueContract):
    """Protected server input description; no archive/credential/approval permission DTO."""

    request: CompanyModelRequest
    context: AssembledContext
    binding: CodingBinding
    scope: BrainReadScope
    sources: tuple[CodingSourceRef, ...]
    input_recipe: ModelInputRecipe
    input_estimate: InputEstimate
    admission_sha256: SHA256
    request_sha256: SHA256
    model_parameters_sha256: SHA256

    @model_validator(mode="after")
    def exact_preparation(self) -> Self:
        call, context, scope = self.request, self.context, self.scope
        manifest, binding, authority = context.manifest, self.binding, context.manifest.authority
        require_coding_sources(binding, context, self.sources)
        if (
            call.tools
            or call.output_schema != coding_schema(binding, manifest=manifest)
            or request_hash(call) != self.request_sha256
            or coding_parameters_sha256(call, self.input_recipe) != self.model_parameters_sha256
            or (call.input_text, call.system_text) != (context.input_text, context.system_text)
            or (call.company_id, call.actor_id, call.task_id, call.trace_id)
            != (scope.company_id, scope.principal_id, scope.task_id, scope.task_trace_id)
            or (
                binding.goal.company_id,
                binding.actor_id,
                binding.workspace_id,
                binding.task_id,
                binding.trace_id,
            )
            != (
                scope.company_id,
                scope.principal_id,
                scope.workspace_id,
                scope.task_id,
                scope.task_trace_id,
            )
            or (manifest.principal_id, manifest.operation_id, manifest.trace_id)
            != (scope.principal_id, scope.operation_id, scope.trace_id)
            or call.actor_id != scope.actor_id
            or call.attempt_id != call.action_id
            or call.data_classification != manifest.data_classification
            or self.input_recipe.profile != "engineering"
            or (authority.model_profile, authority.model_recipe, authority.model_recipe_revision)
            != ("engineering", self.input_recipe.recipe_id, self.input_recipe.revision)
            or self.input_estimate.whole_request is None
        ):
            raise ValueError("Coding schema/scope/source/profile/whole-request fingerprint differs")
        require_input_estimate(call, self.input_estimate, self.input_recipe)
        return self


def require_coding_registry(
    prepared: PreparedCodingRequest, registry: ModelRegistry
) -> ModelRegistration:
    """Join exact approved whole-input registry/model/recipe values; grant no eligibility."""
    prepared = PreparedCodingRequest.model_validate_json(prepared.model_dump_json(by_alias=True))
    registry = ModelRegistry.model_validate_json(registry.model_dump_json())
    call, whole = prepared.request, prepared.input_estimate.whole_request
    model = next((row for row in registry.models if row.registry_id == call.registry_id), None)
    if (
        model is None
        or whole is None
        or (
            registry.company_id,
            registry.revision,
            registry.pricebook_version,
            canonical_sha256(registry),
            canonical_sha256(model),
        )
        != (
            call.company_id,
            call.registry_revision,
            call.price_version,
            whole.registry_sha256,
            whole.model_sha256,
        )
    ):
        raise ValueError("Coding request differs from its original whole-input registry/model")
    return model


def _configuration(prepared: PreparedCodingRequest, catalog: PlanAdmissionCatalog) -> None:
    admission = configured_nexus_admission(catalog)
    if not isinstance(admission, NexusCodingAdmission):
        raise ValueError("Coding requires the exact separately configured full-company admission")
    slot, binding = admission.slots[1], prepared.binding
    bound = slot.child.binding
    if (
        prepared.admission_sha256 != canonical_sha256(admission)
        or binding.goal != admission.goal
        or binding.plan.plan_id != admission.plan_id
        or (
            binding.goal.company_id,
            binding.workspace_id,
            binding.task_id,
            binding.trace_id,
            binding.run_id,
            binding.actor_id,
        )
        != (
            bound.company_id,
            bound.workspace_id,
            bound.task_id,
            bound.trace_id,
            bound.run_id,
            bound.actor_id,
        )
        or (bound.workflow_name, bound.workflow_version, bound.model_profile)
        != ("company.coding.v1", "v1", "engineering")
        or slot.tool.resource != "model:" + prepared.request.registry_id
    ):
        raise ValueError("Coding request differs from its original complete C role/family")
    require_coding_registry(prepared, catalog.models)


def prepare_coding_request(
    call: CompanyModelRequest,
    context: AssembledContext,
    binding: CodingBinding,
    *,
    scope: BrainReadScope,
    sources: tuple[CodingSourceRef, ...],
    input_recipe: ModelInputRecipe,
    catalog: PlanAdmissionCatalog,
    input_estimator: FullContextInputEstimator,
) -> PreparedCodingRequest:
    """Before owner decision, freeze complete source/context/schema and actual full estimate.

    The later concrete producer MUST first verify actual committed_archive plus its
    selected-byte join and retain that read/proof under the original window. This
    description is not that producer's durable source-proof permission.
    """
    if type(input_estimator) is not FullContextInputEstimator:
        raise ValueError("Coding preparation needs the actual full-context estimator")
    admission = configured_nexus_admission(catalog)
    if not isinstance(admission, NexusCodingAdmission):
        raise ValueError("Coding cannot use ordinary or old six-role preparation")
    prepared = PreparedCodingRequest(
        request=call,
        context=context,
        binding=binding,
        scope=scope,
        sources=sources,
        input_recipe=input_recipe,
        input_estimate=input_estimator.estimate(call, catalog.models, input_recipe),
        admission_sha256=canonical_sha256(admission),
        request_sha256=request_hash(call),
        model_parameters_sha256=coding_parameters_sha256(call, input_recipe),
    )
    prepared = PreparedCodingRequest.model_validate_json(prepared.model_dump_json(by_alias=True))
    _configuration(prepared, catalog)
    return prepared


class CodingIntentCheck:
    """Concrete source/context and actual current Goal/approved plan; no issued permit."""

    def __init__(
        self,
        context_check: BrainModelContextCheck,
        prepared: PreparedCodingRequest,
        *,
        registry: ModelRegistry,
    ) -> None:
        if (
            type(context_check) is not BrainModelContextCheck
            or type(context_check._revalidator) is not PersistentContextAssembler
        ):
            raise ValueError("Coding requires its real Brain check/context assembler")
        contexts = context_check._revalidator
        if type(contexts._authority) is not ManagementPlanningAuthority:
            raise ValueError("Coding requires its current actual managed C authority")
        self._context_check = context_check
        self._prepared = PreparedCodingRequest.model_validate_json(
            prepared.model_dump_json(by_alias=True)
        )
        self._registry = ModelRegistry.model_validate_json(registry.model_dump_json())
        self._objects = (
            context_check,
            contexts,
            contexts._authority,
            contexts._authority.management,
        )
        self._pins = self.fingerprint()
        CodingIntentCheck.require_composition(self)

    @property
    def registry(self) -> ModelRegistry:
        return self._registry

    def fingerprint(self) -> tuple[object, ...]:
        check = self._context_check
        return (
            self._prepared.model_dump_json(by_alias=True),
            self._registry.model_dump_json(),
            check.context.model_dump_json(),
            check._lease,
            check._identity,
            check._scope,
            check._request,
            check._recipe,
            check._classification,
        )

    def require_composition(self) -> None:
        check = self._context_check
        contexts = check._revalidator
        if (
            type(check) is not BrainModelContextCheck
            or type(contexts) is not PersistentContextAssembler
            or type(contexts._authority) is not ManagementPlanningAuthority
        ):
            raise ValueError("Original coding context composition changed")
        authority = contexts._authority
        if (
            any(
                a is not b
                for a, b in zip(
                    self._objects, (check, contexts, authority, authority.management), strict=True
                )
            )
            or self.fingerprint() != self._pins
        ):
            raise ValueError("Original coding dependencies or captured values changed")
        authority._require_original()
        if (
            authority.policy.workflow_name,
            authority.policy.workflow_version,
            authority.policy.model_profile,
        ) != (
            "company.coding.v1",
            "v1",
            "engineering",
        ) or authority.recipe != self._prepared.input_recipe:
            raise ValueError("Coding uses another role's actual authority/recipe")
        if (
            check.context != self._prepared.context
            or self._registry != authority.management.catalog.models
        ):
            raise ValueError("Coding context/catalog differs from its frozen preparation")
        lease, binding = check._lease, self._prepared.binding
        if (
            lease.company_id,
            lease.task_id,
            lease.trace_id,
            lease.run_id,
            lease.actor_id,
            lease.workspace_id,
        ) != (
            binding.goal.company_id,
            binding.task_id,
            binding.trace_id,
            binding.run_id,
            binding.actor_id,
            binding.workspace_id,
        ):
            raise ValueError("Coding lease differs from its original registered C binding")
        check._require_snapshot_binding()
        _configuration(self._prepared, authority.management.catalog)

    # The locked original-context/native Goal/plan joins stay adjacent (>50 lines)
    # so each actual await is followed by the same original-composition denial.
    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        self.require_composition()
        await self._context_check.validate(session, control, work, action, now)
        self.require_composition()
        prepared, binding = self._prepared, self._prepared.binding
        if not session.in_transaction() or (control.company_id, work.company_id, work.task_id) != (
            binding.goal.company_id,
            binding.goal.company_id,
            binding.task_id,
        ):
            raise ValueError("Coding needs its original native company transaction/work")
        bound = await ManagementPlanStore.current_binding(session, control.company_id, work.task_id)
        self.require_composition()
        head = await session.get(ManagementGoalHead, (control.company_id, binding.goal.goal_id))
        self.require_composition()
        goal = await session.get(
            ManagementGoalRevision, (control.company_id, binding.goal.revision_id)
        )
        self.require_composition()
        native = await session.get(
            ManagementPlanRevision, (control.company_id, binding.plan.plan_revision_id)
        )
        self.require_composition()
        if (
            bound is None
            or bound.plan != binding.plan
            or head is None
            or not head.active
            or goal is None
            or native is None
        ):
            raise ValueError("Current approved coding plan/goal is unavailable")
        record = plan_record(native)
        if (
            head.current_revision_id != binding.goal.revision_id
            or (goal.company_id, goal.goal_id, goal.revision_id, goal.version, goal.sha256)
            != (
                binding.goal.company_id,
                binding.goal.goal_id,
                binding.goal.revision_id,
                binding.goal.version,
                binding.goal.sha256,
            )
            or plan_reference(record) != binding.plan
            or record.payload.coding_admission_sha256 != prepared.admission_sha256
        ):
            raise ValueError("Coding Goal/head/full-admission plan fingerprint changed")
        contexts = self._context_check._revalidator
        if (
            type(contexts) is not PersistentContextAssembler
            or type(contexts._authority) is not ManagementPlanningAuthority
        ):
            raise ValueError("Original coding context authority changed")
        catalog = contexts._authority.management.catalog
        admission = configured_nexus_admission(catalog)
        assert isinstance(admission, NexusCodingAdmission)
        if select_configured_nexus_plan(catalog, record.payload) != "execution" or (
            bound.child,
            bound.work,
            bound.procedure_id,
        ) != (admission.slots[1].child, admission.slots[1].work, admission.procedure.procedure_id):
            raise ValueError("Coding actual native work differs from its complete approved family")
        self.require_composition()
