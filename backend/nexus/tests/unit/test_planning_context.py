"""Actual request/whole-input proof construction with supplied context, no registered DB proof."""

from pathlib import Path

from nexus.company.brain.context import ContextLimits
from nexus.company.brain.context_render import render_context
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.planning_content import PlanningBinding
from nexus.company.management.planning_intent import require_planning_registry
from nexus.execution.planning_context import prepare_content
from nexus.tests.unit.test_company_brain_context_render import head, material
from nexus.tests.unit.test_company_planning_intent import prepared_inputs
from nexus.tests.unit.test_planning_services import services


def test_server_request_binds_whole_context_goal_head_and_registry_before_approval(
    tmp_path: Path,
) -> None:
    configured = services(tmp_path)
    _, old, binding, scope, _, lease = prepared_inputs()
    authority = old.manifest.authority.model_copy(
        update={
            "model_recipe": configured.recipe.recipe_id,
            "model_recipe_revision": configured.recipe.revision,
        }
    )
    item = material()
    context = render_context(
        scope,
        authority,
        ContextLimits(policy_version="context-v1"),
        (item,),
        (head(item),),
        question="Current goal DATA",
    )
    binding = PlanningBinding.model_validate(
        binding.model_dump() | {"context_manifest_sha256": canonical_sha256(context.manifest)}
    )
    prepared = prepare_content(configured, lease, scope, context, binding)
    assert prepared.input_estimate is not None
    assert prepared.input_estimate.whole_request is not None
    assert prepared.request.bounds.input_tokens == 400_000
    assert prepared.request.bounds.max_output_tokens == 256
    assert prepared.request.input_text == context.input_text
    assert prepared.request.system_text == context.system_text
    assert prepared.request.actor_id == lease.actor_id
    assert prepared.request.attempt_id == prepared.request.action_id
    assert prepared.binding == binding
    require_planning_registry(prepared, configured.management.catalog.models)
