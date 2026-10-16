import type { ActionReview } from '@/types/company'
import type { CodingInputReview, CodingLifecycleStatus } from '@/types/companyCoding'

const prefix = 'coding.prepared:'
const digest = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value)
const parameterKeys = ['request_hash', 'request_id', 'attempt_id', 'registry_id', 'registry_revision',
  'price_version', 'input_recipe_id', 'input_recipe_revision', 'input_recipe_hash'] as const

export function isCodingAction(review: ActionReview): boolean {
  return review.detail?.proposal.tool === 'model.request.v1'
    && review.detail.proposal.preconditions.some(row => row.resource.startsWith(prefix))
}

export function requireCodingInputReview(input: CodingInputReview, review: ActionReview,
  company: string, action: string, proposalHash: string, headerHash: string): void {
  const detail = review.detail, prepared = input.prepared, call = prepared.request
  const estimate = prepared.input_estimate, whole = estimate.whole_request
  if (!detail || review.availability !== 'available' || !isCodingAction(review)) {
    throw new Error('The coding request is unavailable. Refresh its current record.')
  }
  const parameters = detail.proposal.parameters, markers = detail.proposal.preconditions.filter(row => row.resource.startsWith(prefix))
  const cost = Number(input.maximum_reservation_usd)
  if (input.company_id !== company || review.company_id !== company
    || input.action_id !== action || review.audit.action_id !== action
    || input.proposal_sha256 !== proposalHash || review.audit.proposal_sha256 !== proposalHash
    || detail.proposal_sha256 !== proposalHash || input.header_sha256 !== headerHash
    || input.proposal.company_id !== company || input.proposal.action_id !== action
    || Object.keys(parameters).length !== parameterKeys.length
    || Object.keys(input.proposal.parameters).length !== parameterKeys.length
    || parameterKeys.some(key => input.proposal.parameters[key] !== parameters[key])
    || call.company_id !== company || call.action_id !== action || call.attempt_id !== action
    || call.task_id !== detail.task_id || call.trace_id !== detail.trace_id
    || call.actor_id !== detail.proposal.actor_id || prepared.binding.actor_id !== call.actor_id
    || prepared.binding.task_id !== call.task_id || prepared.binding.trace_id !== call.trace_id
    || prepared.binding.goal.company_id !== company
    || input.reference.company_id !== company || input.reference.action_id !== action
    || input.reference.request_sha256 !== input.request_sha256
    || input.reference.header.company_id !== company || input.reference.header.sha256 !== headerHash
    || input.request_sha256 !== prepared.request_sha256 || parameters.request_hash !== input.request_sha256
    || parameters.request_id !== call.request_id || parameters.attempt_id !== call.attempt_id
    || parameters.registry_id !== call.registry_id || parameters.registry_revision !== call.registry_revision
    || input.model.registry_id !== call.registry_id
    || parameters.price_version !== call.price_version || detail.proposal.resource !== `model:${call.registry_id}`
    || parameters.input_recipe_id !== prepared.input_recipe.recipe_id
    || parameters.input_recipe_revision !== prepared.input_recipe.revision
    || estimate.request_hash !== input.request_sha256 || estimate.registry_id !== call.registry_id
    || estimate.registry_revision !== call.registry_revision
    || estimate.recipe_id !== prepared.input_recipe.recipe_id || estimate.recipe_revision !== prepared.input_recipe.revision
    // Whole-input and native action recipe hashes have different canonical domains.
    || !whole || !digest(whole.recipe_sha256) || !digest(parameters.input_recipe_hash)
    || whole.tokens !== call.bounds.input_tokens || whole.method !== call.bounds.input_bound_kind
    || whole.conformance_reference !== prepared.input_recipe.conformance_reference
    || prepared.context.input_text !== call.input_text || prepared.context.system_text !== call.system_text
    || call.tools.length !== 0 || markers.length !== 1 || markers[0].resource !== `${prefix}${action}`
    || markers[0].revision !== `sha256:${headerHash}:bytes:${input.reference.header.byte_length}`
    || !Number.isFinite(cost) || cost < 0 || cost > 5 || cost !== Number(detail.proposal.estimated_cost_usd)
    || input.company_completed !== false || input.execution_permitted !== false) {
    throw new Error('The coding input no longer matches the reviewed request. Refresh before deciding.')
  }
}

export function canDecideCoding(review: ActionReview, paused: boolean): boolean {
  return !paused && review.availability === 'available' && isCodingAction(review)
    && !review.audit.owner_decision && !review.audit.consumed_at
    && ['proposed', 'validated', 'awaiting_approval'].includes(review.audit.state)
}

export function canPrepareCoding(status: CodingLifecycleStatus): boolean {
  return status.approved_r2 && status.current !== null && !status.resources_pending
    && !status.action_id && !status.workflow_id && status.native_state === null && status.work_state === 'eligible'
}

export function canDispatchCoding(status: CodingLifecycleStatus, review: ActionReview, now = Date.now()): boolean {
  const decision = review.audit.owner_decision
  return status.company_id === review.company_id && status.action_id === review.audit.action_id
    && status.proposal_sha256 === review.audit.proposal_sha256 && review.availability === 'available'
    && isCodingAction(review) && status.approved_r2 && status.current !== null
    && !status.resources_pending && !status.workflow_id && status.native_state === null
    && status.work_state === 'awaiting_approval' && !review.audit.consumed_at
    && decision?.decision === 'approved' && decision.action_id === status.action_id
    && decision.action_hash === status.proposal_sha256 && Date.parse(decision.issued_at) <= now
    && Date.parse(decision.expires_at) > now
}

export function canRecoverCodingWait(status: CodingLifecycleStatus, review: ActionReview): boolean {
  return status.company_id === review.company_id && review.availability === 'available' && isCodingAction(review)
    && status.approved_r2 && status.current !== null && !status.resources_pending
    && status.action_id === review.audit.action_id && status.proposal_sha256 === review.audit.proposal_sha256
    && !status.workflow_id && status.native_state === null && !review.audit.owner_decision
    && !review.audit.consumed_at && status.action_state === 'awaiting_approval'
    && ['running', 'blocked', 'eligible'].includes(status.work_state ?? '')
}

export function codingStage(status: CodingLifecycleStatus): string {
  if (status.resources_pending) return 'Finishing owned operations'
  if (status.native_state === 'intent' || status.native_state === 'outcome_unknown') return 'Outcome unconfirmed; reservation remains held'
  if (status.native_state === 'failed') return 'Coding call failed; inspect recorded costs'
  if (status.native_state === 'succeeded') return 'Recorded patch awaits independent verification'
  if (status.workflow_id) return 'Dispatched; outcome unconfirmed'
  if (!status.approved_r2) return 'Approve the complete operating plan first'
  if (status.action_id) return 'Exact coding request saved'
  if (status.work_state === 'blocked') return 'Coding is blocked'
  return 'Coding input has not been prepared'
}
