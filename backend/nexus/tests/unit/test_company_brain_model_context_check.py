"""Per-call Brain guard snapshots exact trusted inputs without minting token authority."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.context import AssembledContext, ContextLimits, ContextManifest
from nexus.company.brain.context_render import render_context
from nexus.company.brain.model_context_check import BrainModelContextCheck
from nexus.company.brain.sources import SourceHead
from nexus.company.contracts.actions import ResourceRevision
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.harness.journal_models import CompanyControl
from nexus.tests.unit.test_company_brain_context_render import authority, head, material
from nexus.tests.unit.test_company_model_authorizer import recipe
from nexus.tests.unit.test_company_provider_conformance import request


class NoIORevalidator:
    async def revalidate_context(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        manifest: ContextManifest,
        now: datetime,
    ) -> tuple[ResourceRevision, ...]:
        raise AssertionError("Constructor must not use DB or perform I/O")


def inputs() -> tuple[BrainReadScope, AssembledContext, ExecutionLease]:
    scope = BrainReadScope(
        company_id=UUID(int=1),
        workspace_id=UUID(int=2),
        principal_id=UUID(int=3),
        operation_id=UUID(int=4),
        trace_id=UUID(int=5),
        task_id=UUID(int=6),
        task_trace_id=UUID(int=7),
        actor_id=UUID(int=3),
    )
    current = authority().model_copy(
        update={
            "model_profile": recipe().profile,
            "model_recipe": recipe().recipe_id,
            "model_recipe_revision": recipe().revision,
        }
    )
    item = material()
    heads: tuple[SourceHead, ...] = (head(item),)
    context = render_context(
        scope,
        current,
        ContextLimits(policy_version="context-v1"),
        (item,),
        heads,
        question="Read exact context",
    )
    lease = ExecutionLease(
        company_id=scope.company_id,
        task_id=UUID(int=6),
        trace_id=UUID(int=7),
        actor_id=scope.principal_id,
        workspace_id=scope.workspace_id,
        run_id=UUID(int=8),
        workflow_version="test-v1",
        segment_id=UUID(int=9),
        worker_id=UUID(int=10),
        fence=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
        mode="execute",
    )
    return scope, context, lease


def test_readonly_context_remains_unqualified_when_bound_to_explicit_model_recipe() -> None:
    scope, context, lease = inputs()
    call = request(
        task_id=lease.task_id,
        trace_id=lease.trace_id,
        actor_id=lease.actor_id,
        attempt_id=UUID(int=5),
        data_classification="confidential",
        input_text=context.input_text,
        system_text=context.system_text,
    )
    check = BrainModelContextCheck(
        NoIORevalidator(),
        context,
        scope,
        VerifiedIdentity(principal_id=lease.actor_id, workspace_id=lease.workspace_id),
        call,
        recipe(),
        lease,
        allowed_classification="confidential",
    )
    assert check.context.manifest.token_qualification == "unavailable"
    assert check.context.manifest.qualified_input_tokens is None


@pytest.mark.parametrize(
    "splice",
    [
        "input",
        "system",
        "scope",
        "identity",
        "recipe",
        "class",
        "task",
        "actor",
        "workspace",
        "profile",
        "audit",
        "unbound",
    ],
)
def test_context_request_scope_identity_recipe_or_class_splicing_is_denied(splice: str) -> None:
    scope, context, lease = inputs()
    call = request(
        task_id=lease.task_id,
        trace_id=lease.trace_id,
        actor_id=lease.actor_id,
        attempt_id=UUID(int=5),
        data_classification="confidential",
        input_text=context.input_text,
        system_text=context.system_text,
    )
    signed = VerifiedIdentity(principal_id=lease.actor_id, workspace_id=lease.workspace_id)
    bound_recipe = recipe()
    if splice == "input":
        call = call.model_copy(update={"input_text": "substituted source"})
    elif splice == "system":
        call = call.model_copy(update={"system_text": "substituted runtime"})
    elif splice == "scope":
        scope = scope.model_copy(update={"task_trace_id": UUID(int=999)})
    elif splice == "identity":
        signed = signed.model_copy(update={"principal_id": UUID(int=999)})
    elif splice == "recipe":
        bound_recipe = bound_recipe.model_copy(update={"revision": "other-recipe"})
    elif splice == "class":
        call = call.model_copy(update={"data_classification": "public"})
    elif splice == "task":
        call = call.model_copy(update={"task_id": UUID(int=999)})
    elif splice == "actor":
        call = call.model_copy(update={"actor_id": UUID(int=999)})
    elif splice == "workspace":
        signed = signed.model_copy(update={"workspace_id": UUID(int=999)})
    elif splice == "profile":
        bound_recipe = bound_recipe.model_copy(update={"profile": "routine"})
    elif splice == "audit":
        scope = scope.model_copy(update={"operation_id": UUID(int=999)})
    else:
        scope = scope.model_copy(update={"task_id": None, "task_trace_id": None, "actor_id": None})
    with pytest.raises(ValueError):
        BrainModelContextCheck(
            NoIORevalidator(),
            context,
            scope,
            signed,
            call,
            bound_recipe,
            lease,
            allowed_classification="confidential",
        )
