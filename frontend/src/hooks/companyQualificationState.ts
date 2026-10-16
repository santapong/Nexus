import type { QualificationStatus } from '@/types/companyQualification'

const stopped = new Set(['blocked', 'outcome_unknown', 'cancelled', 'completed'])
const after = (value: string, observed: string) => Number.isFinite(Date.parse(value))
  && Number.isFinite(Date.parse(observed)) && Date.parse(value) > Date.parse(observed)
const sameRecipe = (status: QualificationStatus) => typeof status.recipe.recipe_sha256 === 'string'
  && status.recipe.recipe_sha256 === status.action.proposal.parameters.recipe_sha256

export function requireQualificationReview(status: QualificationStatus, company: string, action: string, hash: string) {
  const proposal = status.action.proposal
  const work = status.work.registration.work
  if (status.action.company_id !== company || proposal.company_id !== company
    || status.work.company_id !== company || work.company_id !== company
    || proposal.action_id !== action || status.action.proposal_hash !== hash
    || proposal.task_id !== work.task_id || proposal.trace_id !== work.trace_id
    || proposal.tool !== 'model.qualify.v1' || proposal.tool_version !== 'v1'
    || status.work.registration.workflow_name !== 'company.model-qualification.v1'
    || status.work.registration.model_profile !== 'qualification-only.v1' || !sameRecipe(status)) {
    throw new Error('This check no longer matches the reviewed company, input or proposal. Refresh before deciding.')
  }
}

export function canDecideQualification(status: QualificationStatus, paused: boolean, approved: boolean) {
  return !paused && sameRecipe(status) && !stopped.has(status.work.state)
    && !status.effect && !status.dispatch && status.action.state === 'awaiting_approval'
    && status.action.consumed_at == null && status.action.approval == null
    && (!approved || (status.recipe.availability === 'current'
      && after(status.recipe.expires_at, status.observed_at)))
}

export function canDispatchQualification(status: QualificationStatus, paused: boolean) {
  const approval = status.action.approval
  return !paused && sameRecipe(status) && !stopped.has(status.work.state)
    && !status.effect && !status.dispatch && status.action.state === 'awaiting_approval'
    && status.action.consumed_at == null && approval?.decision === 'approved'
    && status.recipe.availability === 'current' && after(approval.expires_at, status.observed_at)
    && after(status.recipe.expires_at, status.observed_at)
}

export function qualificationPhase(status: QualificationStatus) {
  if (status.effect?.state === 'outcome_unknown' || status.hold?.state === 'unknown') return 'unknown'
  if (status.effect?.state === 'failed') return 'stopped'
  if (status.effect?.state === 'succeeded') return 'recorded'
  if (status.work.state === 'outcome_unknown') return 'unknown'
  if (stopped.has(status.work.state)) return 'stopped'
  if (status.effect?.state === 'intent' || status.dispatch) return 'dispatched'
  if (status.action.state === 'rejected') return 'rejected'
  const approval = status.action.approval
  if (approval?.decision === 'approved' && !after(approval.expires_at, status.observed_at)) return 'expired'
  if (status.action.consumed_at != null) return 'reserved'
  if (status.recipe.availability !== 'current' || !after(status.recipe.expires_at, status.observed_at)) return 'unavailable'
  if (approval?.decision === 'approved') return 'approved'
  return 'awaiting_approval'
}

export const qualificationLabels = {
  unknown: 'Usage unconfirmed', stopped: 'Check stopped', recorded: 'Response recorded',
  dispatched: 'Dispatched', rejected: 'Rejected', expired: 'Approval expired',
  reserved: 'Authorized reservation', unavailable: 'Preparation unavailable',
  approved: 'Approved', awaiting_approval: 'Owner review',
} as const
