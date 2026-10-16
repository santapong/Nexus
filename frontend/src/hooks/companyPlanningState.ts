import type { ActionReview } from '@/types/company'
import type { PlanningInputReview, PlanningLifecycleStatus } from '@/types/companyPlanning'

const prefix = 'planning.prepared:'
const digest = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value)

export function isPlanningAction(review: ActionReview): boolean {
  return review.detail?.proposal.tool === 'model.request.v1'
    && review.detail.proposal.preconditions.some(row => row.resource.startsWith(prefix))
}

export function requirePlanningInputReview(input: PlanningInputReview, review: ActionReview,
  company: string, action: string, proposalHash: string, descriptorHash: string): void {
  const detail = review.detail
  const prepared = input.prepared
  const call = prepared.request
  const estimate = prepared.input_estimate
  const whole = estimate?.whole_request
  if (!detail || review.availability !== 'available' || !isPlanningAction(review)) {
    throw new Error('The planning request is unavailable. Refresh its current record.')
  }
  const parameters = detail.proposal.parameters
  const markers = detail.proposal.preconditions.filter(row => row.resource.startsWith(prefix))
  const cost = Number(input.maximum_reservation_usd)
  if (review.company_id !== company || input.company_id !== company
    || input.action_id !== action || review.audit.action_id !== action
    || input.proposal_sha256 !== proposalHash || review.audit.proposal_sha256 !== proposalHash
    || detail.proposal_sha256 !== proposalHash || input.descriptor_sha256 !== descriptorHash
    || detail.proposal.company_id !== company || detail.proposal.action_id !== action
    || call.company_id !== company || call.action_id !== action || call.attempt_id !== action
    || call.task_id !== detail.task_id || call.trace_id !== detail.trace_id
    || call.actor_id !== detail.proposal.actor_id || prepared.binding.goal.company_id !== company
    || input.request_sha256 !== prepared.request_sha256 || parameters.request_hash !== input.request_sha256
    || parameters.request_id !== call.request_id || parameters.attempt_id !== call.attempt_id
    || parameters.registry_id !== call.registry_id || parameters.registry_revision !== call.registry_revision
    || parameters.price_version !== call.price_version || detail.proposal.resource !== `model:${call.registry_id}`
    || parameters.input_recipe_id !== prepared.input_recipe.recipe_id
    || parameters.input_recipe_revision !== prepared.input_recipe.revision
    || !estimate || !whole || estimate.request_hash !== input.request_sha256
    || estimate.registry_id !== call.registry_id || estimate.registry_revision !== call.registry_revision
    || estimate.recipe_id !== prepared.input_recipe.recipe_id || estimate.recipe_revision !== prepared.input_recipe.revision
    // These are different canonical domains. The server verifies all nine native parameters.
    || !digest(whole.recipe_sha256) || !digest(parameters.input_recipe_hash)
    || whole.tokens !== call.bounds.input_tokens
    || whole.method !== call.bounds.input_bound_kind
    || whole.conformance_reference !== prepared.input_recipe.conformance_reference
    || prepared.context.input_text !== call.input_text || prepared.context.system_text !== call.system_text
    || call.tools.length !== 0
    || markers.length !== 1 || !markers[0].revision.startsWith(`sha256:${descriptorHash}:bytes:`)
    || !Number.isFinite(cost) || cost < 0 || cost > 5 || cost !== Number(detail.proposal.estimated_cost_usd)
    || input.company_completed !== false || input.execution_permitted !== false) {
    throw new Error('The planning input no longer matches the reviewed request. Refresh before deciding.')
  }
}

export function canDecidePlanning(review: ActionReview, paused: boolean): boolean {
  return !paused && review.availability === 'available' && Boolean(review.detail)
    && isPlanningAction(review) && !review.audit.owner_decision
    && ['proposed', 'awaiting_approval', 'validated'].includes(review.audit.state)
}

export function planningStage(status: PlanningLifecycleStatus): string {
  if (status.resources_pending) return 'Finishing owned operations'
  if (status.native_state === 'outcome_unknown' || status.native_state === 'intent') return 'Outcome unconfirmed; reservation remains held'
  if (status.current_state === 'revoked') return 'Plan revoked; recorded outcomes remain'
  if (status.native_state === 'failed') return 'Model call failed'
  if (status.formal_proposal) return status.current_state === 'approved'
    && status.current?.plan_revision_id === status.formal_proposal.plan_revision_id
    ? 'Formal plan approved; execution is separate' : 'Formal proposal awaits owner review'
  if (status.native_state === 'succeeded') return 'Recorded model output available for review'
  if (status.work_state === 'blocked') return 'Planning is blocked'
  if (status.workflow_id) return 'Dispatched; no confirmed model result'
  if (status.owner_decision === 'rejected') return 'Planning request rejected'
  if (status.owner_decision === 'approved') return 'Input decision saved; not dispatched'
  if (status.action_id) return 'Saved model input awaits owner review'
  if (status.current_state === 'approved') return 'Planning work approved; input not prepared'
  if (status.bootstrap) return 'Planning-only proposal awaits approval'
  return 'No planning-only proposal recorded'
}

export function canPreparePlanning(status: PlanningLifecycleStatus): boolean {
  return !status.resources_pending && !status.action_id && !status.workflow_id
    && status.work_state === 'eligible'
    && status.current_state === 'approved' && status.bootstrap !== null
    && status.current?.plan_revision_id === status.bootstrap.plan_revision_id
}

export function canDispatchPlanning(status: PlanningLifecycleStatus, now = Date.now()): boolean {
  return !status.resources_pending && Boolean(status.action_id && status.proposal_sha256)
    && status.work_state === 'awaiting_approval'
    && status.native_state === null && status.current_state === 'approved'
    && status.current?.plan_revision_id === status.bootstrap?.plan_revision_id
    && !status.workflow_id && status.owner_decision === 'approved'
    && status.owner_decision_expires_at !== null && Date.parse(status.owner_decision_expires_at) > now
}

export function canRequestPlanningWaitRecovery(status: PlanningLifecycleStatus): boolean {
  // Visibility is only a request hint; the native recovery checks actual eligibility.
  return !status.resources_pending && Boolean(status.action_id && status.proposal_sha256)
    && status.current !== null && !status.workflow_id && status.native_state === null
    && status.action_state === 'awaiting_approval' && status.owner_decision === null
    && ['running', 'blocked', 'eligible'].includes(status.work_state ?? '')
}
